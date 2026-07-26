"""Auditable GEMBA-MQM quality gate with independent judges and safe refinement."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.review_agents import (
    DEFAULT_SENSENOVA_URL,
    _json_object,
    load_glossary_prompt,
    model_chat,
)


MQM_DIMENSIONS = {
    "accuracy": {
        "weight": 0.35,
        "name": "准确性",
        "description": "错译、漏译、增译、主客体、否定、时态和语气",
    },
    "fluency": {
        "weight": 0.25,
        "name": "流畅度",
        "description": "中文语法、自然度、简洁度和字幕可读性",
    },
    "terminology": {
        "weight": 0.20,
        "name": "术语",
        "description": "角色名、称呼、专名和前后译法一致性",
    },
    "style": {
        "weight": 0.20,
        "name": "风格",
        "description": "人物语气、关系、情绪和动漫口语风格",
    },
}
SEVERITIES = {"none", "minor", "major", "critical"}
RECOMMENDATIONS = {"keep", "revise"}
PROMPT_VERSION = "gemba-mqm-dual-judge-v3"
MAX_INCOMPLETE_PASSES = 3


DIMENSION_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 100},
        "severity": {"type": "string", "enum": sorted(SEVERITIES)},
        "reason": {"type": "string"},
    },
    "required": ["score", "severity", "reason"],
    "additionalProperties": False,
}
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "object",
            "properties": {key: DIMENSION_SCHEMA for key in MQM_DIMENSIONS},
            "required": list(MQM_DIMENSIONS),
            "additionalProperties": False,
        },
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(MQM_DIMENSIONS)},
                    "severity": {"type": "string", "enum": sorted(SEVERITIES - {"none"})},
                    "source_span": {"type": "string"},
                    "target_span": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": [
                    "category", "severity", "source_span", "target_span", "explanation"
                ],
                "additionalProperties": False,
            },
        },
        "recommendation": {"type": "string", "enum": sorted(RECOMMENDATIONS)},
        "suggested_zh": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "dimensions", "errors", "recommendation", "suggested_zh", "confidence"
    ],
    "additionalProperties": False,
}
EDITOR_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["keep", "revise"]},
        "corrected_zh": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["decision", "corrected_zh", "reason", "confidence"],
    "additionalProperties": False,
}


@dataclass
class MQMConfig:
    provider: str = "openai"
    host: str = "localhost"
    base_url: str = DEFAULT_SENSENOVA_URL
    api_key_file: str = "config/sensenova_apikeys"
    judge_models: list[str] = field(
        default_factory=lambda: [
            "sensenova-6.7-flash-lite",
            "deepseek-v4-flash",
        ]
    )
    judge_fallback_models: dict[str, str] = field(default_factory=dict)
    editor_model: str = "sensenova-6.7-flash-lite"
    editor_fallback_model: str = ""
    max_workers: int = 2
    context_window: int = 5
    review_threshold: float = 80.0
    min_judge_confidence: float = 0.75
    min_editor_confidence: float = 0.85
    min_final_score: float = 80.0
    min_improvement: float = 5.0
    retries: int = 4
    timeout_s: int = 600

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "MQMConfig":
        if not data:
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in data.items() if key in known})

    def validate(self) -> "MQMConfig":
        self.provider = self.provider.strip().lower()
        if self.provider not in {"openai", "ollama"}:
            raise ValueError("provider must be openai or ollama")
        if len(self.judge_models) < 2 or len(set(self.judge_models)) < 2:
            raise ValueError("judge_models must contain at least two distinct models")
        self.judge_fallback_models = {
            str(primary).strip(): str(fallback).strip()
            for primary, fallback in self.judge_fallback_models.items()
            if str(primary).strip() and str(fallback).strip()
        }
        self.editor_fallback_model = self.editor_fallback_model.strip()
        for primary, fallback in self.judge_fallback_models.items():
            if primary not in self.judge_models:
                raise ValueError(
                    f"judge fallback primary model is not configured: {primary}"
                )
            if fallback in self.judge_models:
                raise ValueError(
                    "judge fallback models must remain distinct from all primary judges"
                )
        if len(set(self.judge_fallback_models.values())) != len(
            self.judge_fallback_models
        ):
            raise ValueError("judge fallback models must be distinct")
        if self.max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if self.context_window < 0:
            raise ValueError("context_window must be >= 0")
        if self.retries < 1:
            raise ValueError("retries must be >= 1")
        for name in ("min_judge_confidence", "min_editor_confidence"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        for name in ("review_threshold", "min_final_score"):
            value = getattr(self, name)
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.min_improvement < 0:
            raise ValueError("min_improvement must be >= 0")
        return self

    def signature(self) -> str:
        value = asdict(self)
        value.pop("judge_fallback_models", None)
        value.pop("editor_fallback_model", None)
        value["prompt_version"] = PROMPT_VERSION
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]


def _exact_keys(value: dict, expected: set[str], label: str) -> None:
    keys = set(value)
    if keys != expected:
        raise ValueError(
            f"{label} fields mismatch; missing={sorted(expected - keys)}, "
            f"extra={sorted(keys - expected)}"
        )


def _number(value, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a JSON number")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return number


def parse_judge_response(response: str) -> dict:
    value, repaired = _json_object(response)
    _exact_keys(
        value,
        {"dimensions", "errors", "recommendation", "suggested_zh", "confidence"},
        "MQM judge",
    )
    if not isinstance(value["dimensions"], dict):
        raise ValueError("MQM dimensions must be an object")
    _exact_keys(value["dimensions"], set(MQM_DIMENSIONS), "MQM dimensions")
    dimensions = {}
    for name in MQM_DIMENSIONS:
        dimension = value["dimensions"][name]
        if not isinstance(dimension, dict):
            raise ValueError(f"MQM dimension {name} must be an object")
        _exact_keys(dimension, {"score", "severity", "reason"}, f"MQM {name}")
        severity = dimension["severity"]
        if severity not in SEVERITIES or not isinstance(dimension["reason"], str):
            raise ValueError(f"invalid MQM {name} severity or reason")
        dimensions[name] = {
            "score": _number(dimension["score"], 0, 100, f"MQM {name} score"),
            "severity": severity,
            "reason": dimension["reason"].strip(),
        }

    if not isinstance(value["errors"], list):
        raise ValueError("MQM errors must be an array")
    errors = []
    error_keys = (
        "category",
        "severity",
        "source_span",
        "target_span",
        "explanation",
    )
    for item in value["errors"]:
        if not isinstance(item, dict):
            raise ValueError("each MQM error must be an object")
        _exact_keys(item, set(error_keys), "MQM error")
        if item["category"] not in MQM_DIMENSIONS:
            raise ValueError(f"invalid MQM error category: {item['category']!r}")
        if item["severity"] not in SEVERITIES - {"none"}:
            raise ValueError(f"invalid MQM error severity: {item['severity']!r}")
        if not all(
            isinstance(item[key], str)
            for key in ("source_span", "target_span", "explanation")
        ):
            raise ValueError("MQM error spans and explanation must be strings")
        errors.append(
            {
                key: item[key].strip() if isinstance(item[key], str) else item[key]
                for key in error_keys
            }
        )

    recommendation = value["recommendation"]
    suggested = value["suggested_zh"]
    if recommendation not in RECOMMENDATIONS or not isinstance(suggested, str):
        raise ValueError("invalid MQM recommendation or suggested_zh")
    if recommendation == "revise" and not suggested.strip():
        raise ValueError("revise recommendation requires suggested_zh")
    overall = sum(
        dimensions[name]["score"] * MQM_DIMENSIONS[name]["weight"]
        for name in MQM_DIMENSIONS
    )
    return {
        "dimensions": dimensions,
        "errors": errors,
        "recommendation": recommendation,
        "suggested_zh": suggested.strip() or None,
        "confidence": _number(value["confidence"], 0, 1, "MQM confidence"),
        "overall": round(overall, 2),
        "response_repaired": repaired,
    }


def parse_editor_response(response: str) -> dict:
    value, repaired = _json_object(response)
    _exact_keys(
        value, {"decision", "corrected_zh", "reason", "confidence"}, "MQM editor"
    )
    if not all(isinstance(value[key], str) for key in ("decision", "corrected_zh", "reason")):
        raise ValueError("MQM editor text fields must be strings")
    if value["decision"] not in RECOMMENDATIONS:
        raise ValueError(f"invalid MQM editor decision: {value['decision']!r}")
    corrected = value["corrected_zh"].strip()
    if value["decision"] == "revise" and not corrected:
        raise ValueError("MQM editor revise decision requires corrected_zh")
    return {
        "decision": value["decision"],
        "corrected_zh": corrected or None,
        "reason": value["reason"].strip(),
        "confidence": _number(value["confidence"], 0, 1, "MQM editor confidence"),
        "response_repaired": repaired,
    }


def _segment_text(segment: dict) -> str:
    return str(segment.get("text", segment.get("zh", ""))).strip()


def _context(segments: list[dict], position: int, window: int) -> str:
    start = max(0, position - window)
    end = min(len(segments), position + window + 1)
    lines = []
    for index in range(start, end):
        marker = "目标" if index == position else "上下文"
        lines.append(
            f"[{marker} {index}] 日文：{segments[index].get('ja', '')}\n"
            f"[{marker} {index}] 中文：{_segment_text(segments[index])}"
        )
    return "\n".join(lines)


def _context_with_target_translation(context: str, position: int, text: str) -> str:
    """Keep the target line in rescore context consistent with the candidate."""
    prefix = f"[目标 {position}] 中文："
    return "\n".join(
        f"{prefix}{text}" if line.startswith(prefix) else line
        for line in context.splitlines()
    )


def _segment_key(
    position: int, segment: dict, config_signature: str, context: str = ""
) -> str:
    payload = {
        "position": position,
        "ja": segment.get("ja", ""),
        "zh": _segment_text(segment),
        "context": context,
        "config": config_signature,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"{position}:{digest}"


def _call_with_retries(
    messages: list[dict],
    model: str,
    config: MQMConfig,
    parser: Callable[[str], dict],
    schema: dict,
    chat_fn: Callable = model_chat,
) -> tuple[Optional[dict], str, str, int, float]:
    raw = ""
    error = ""
    started = time.time()
    for attempt in range(1, config.retries + 1):
        try:
            raw = chat_fn(
                messages,
                provider=config.provider,
                host=config.host,
                base_url=config.base_url,
                api_key_file=config.api_key_file,
                model=model,
                temperature=0.0,
                json_mode=True,
                json_schema=schema,
                timeout_s=config.timeout_s,
            )
            return parser(raw), raw, "", attempt, time.time() - started
        except Exception as exception:
            error = str(exception)
            if attempt < config.retries:
                time.sleep(min(2 ** (attempt - 1), 4))
    return None, raw, error, config.retries, time.time() - started


def _call_with_model_fallback(
    messages: list[dict],
    model: str,
    fallback_model: str,
    config: MQMConfig,
    parser: Callable[[str], dict],
    schema: dict,
    chat_fn: Callable = model_chat,
) -> tuple[Optional[dict], str, str, int, float, str, bool, str]:
    parsed, raw, error, attempts, elapsed = _call_with_retries(
        messages, model, config, parser, schema, chat_fn
    )
    fallback_model = fallback_model.strip()
    if parsed is not None or not fallback_model or fallback_model == model:
        return parsed, raw, error, attempts, elapsed, model, False, ""

    primary_error = error
    (
        parsed,
        raw,
        fallback_error,
        fallback_attempts,
        fallback_elapsed,
    ) = _call_with_retries(
        messages, fallback_model, config, parser, schema, chat_fn
    )
    if parsed is None:
        error = (
            f"primary {model}: {primary_error}; "
            f"fallback {fallback_model}: {fallback_error}"
        )
    else:
        error = ""
    return (
        parsed,
        raw,
        error,
        attempts + fallback_attempts,
        elapsed + fallback_elapsed,
        fallback_model,
        True,
        primary_error,
    )


def run_judge(
    model: str,
    segment: dict,
    context: str,
    glossary: str,
    config: MQMConfig,
    chat_fn: Callable = model_chat,
) -> dict:
    prompt = f"""依据 GEMBA-MQM 审查目标字幕。不要因个人措辞偏好惩罚正确译文。

上下文：
{context}

目标日文：{segment.get('ja', '')}
目标中文：{_segment_text(segment)}

必须遵守的术语：
{glossary}

四个维度均需给 0-100 分、最高错误严重度 none/minor/major/critical 和理由。
errors 只列真实错误，必须给日文/中文证据片段；没有错误时为空数组。
只有确需改动时 recommendation=revise 并给完整 suggested_zh，否则 keep 且 suggested_zh 为空。

只能输出下面这个 JSON 骨架，所有字段都必须存在，禁止增加字段或改字段名：
{{
  "dimensions": {{
    "accuracy": {{"score": 0, "severity": "critical", "reason": "依据"}},
    "fluency": {{"score": 0, "severity": "none", "reason": "依据"}},
    "terminology": {{"score": 0, "severity": "none", "reason": "依据"}},
    "style": {{"score": 0, "severity": "none", "reason": "依据"}}
  }},
  "errors": [{{
    "category": "accuracy",
    "severity": "critical",
    "source_span": "日文证据",
    "target_span": "中文证据",
    "explanation": "错误说明"
  }}],
  "recommendation": "keep|revise",
  "suggested_zh": "完整建议译文；keep 时为空字符串",
  "confidence": 0.95
}}"""
    (
        parsed,
        raw,
        error,
        attempts,
        elapsed,
        used_model,
        fallback_used,
        primary_error,
    ) = _call_with_model_fallback(
        [
            {
                "role": "system",
                "content": "你是保守、证据优先的日中字幕 GEMBA-MQM 质量裁判。",
            },
            {"role": "user", "content": prompt},
        ],
        model,
        config.judge_fallback_models.get(model, ""),
        config,
        parse_judge_response,
        JUDGE_SCHEMA,
        chat_fn,
    )
    result = {
        "model": used_model,
        "primary_model": model,
        "fallback_used": fallback_used,
        "primary_error": primary_error or None,
        "attempts": attempts,
        "time_s": round(elapsed, 2),
        "raw_response": raw,
    }
    if parsed is None:
        result.update(status="error", error=error, confidence=0.0)
    else:
        result.update(status="ok", **parsed)
    return result


def run_editor(
    segment: dict,
    context: str,
    glossary: str,
    judges: list[dict],
    config: MQMConfig,
    chat_fn: Callable = model_chat,
) -> dict:
    evidence = [
        {
            key: judge.get(key)
            for key in (
                "model",
                "overall",
                "dimensions",
                "errors",
                "recommendation",
                "suggested_zh",
                "confidence",
            )
        }
        for judge in judges
    ]
    prompt = f"""请根据两个独立 MQM 裁判的证据做保守总编决策。

上下文：
{context}

目标日文：{segment.get('ja', '')}
原中文：{_segment_text(segment)}
术语：{glossary}

裁判结果：
{json.dumps(evidence, ensure_ascii=False)}

若只是同义改写、证据矛盾或原译正确，decision=keep。只有能给出更准确完整译文时才 revise。
只能输出下面这个 JSON 骨架，所有字段都必须存在，禁止增加字段或改字段名：
{{
  "decision": "keep|revise",
  "corrected_zh": "完整最终译文；keep 时为空字符串",
  "reason": "简短证据",
  "confidence": 0.95
}}"""
    (
        parsed,
        raw,
        error,
        attempts,
        elapsed,
        used_model,
        fallback_used,
        primary_error,
    ) = _call_with_model_fallback(
        [
            {"role": "system", "content": "你是保守的日中字幕质量总编。"},
            {"role": "user", "content": prompt},
        ],
        config.editor_model,
        config.editor_fallback_model,
        config,
        parse_editor_response,
        EDITOR_SCHEMA,
        chat_fn,
    )
    result = {
        "model": used_model,
        "primary_model": config.editor_model,
        "fallback_used": fallback_used,
        "primary_error": primary_error or None,
        "attempts": attempts,
        "time_s": round(elapsed, 2),
        "raw_response": raw,
    }
    if parsed is None:
        result.update(status="error", error=error, confidence=0.0)
    else:
        result.update(status="ok", **parsed)
    return result


def _run_judges(
    segment: dict,
    context: str,
    glossary: str,
    config: MQMConfig,
    chat_fn: Callable,
) -> list[dict]:
    results = {}
    with ThreadPoolExecutor(max_workers=len(config.judge_models)) as executor:
        futures = {
            executor.submit(
                run_judge, model, segment, context, glossary, config, chat_fn
            ): model
            for model in config.judge_models
        }
        for future in as_completed(futures):
            model = futures[future]
            try:
                results[model] = future.result()
            except Exception as exception:
                results[model] = {
                    "model": model,
                    "status": "error",
                    "error": str(exception),
                    "confidence": 0.0,
                }
    return [results[model] for model in config.judge_models]


def review_segment(
    position: int,
    segment: dict,
    context: str,
    glossary: str,
    config: MQMConfig,
    chat_fn: Callable = model_chat,
) -> dict:
    original = _segment_text(segment)
    judges = _run_judges(segment, context, glossary, config, chat_fn)
    judge_errors = [judge for judge in judges if judge.get("status") != "ok"]
    valid = [judge for judge in judges if judge.get("status") == "ok"]
    baseline_score = min((judge["overall"] for judge in valid), default=0.0)
    issue_votes = sum(
        judge.get("confidence", 0.0) >= config.min_judge_confidence
        and (
            judge.get("recommendation") == "revise"
            or judge.get("overall", 100.0) < config.review_threshold
            or any(
                error.get("severity") in {"major", "critical"}
                for error in judge.get("errors", [])
            )
        )
        for judge in valid
    )

    editor = None
    rescored = []
    if issue_votes and not judge_errors:
        editor = run_editor(segment, context, glossary, judges, config, chat_fn)
        if (
            editor.get("status") == "ok"
            and editor.get("decision") == "revise"
            and editor.get("corrected_zh")
            and editor.get("confidence", 0.0) >= config.min_editor_confidence
        ):
            candidate = dict(segment)
            candidate["text"] = editor["corrected_zh"]
            rescore_context = _context_with_target_translation(
                context, position, editor["corrected_zh"]
            )
            rescored = _run_judges(
                candidate, rescore_context, glossary, config, chat_fn
            )

    rescore_errors = [judge for judge in rescored if judge.get("status") != "ok"]
    final_score = min(
        (judge["overall"] for judge in rescored if judge.get("status") == "ok"),
        default=0.0,
    )
    all_rescorers_accept = bool(rescored) and all(
        judge.get("status") == "ok"
        and judge.get("confidence", 0.0) >= config.min_judge_confidence
        and judge.get("recommendation") == "keep"
        for judge in rescored
    )
    eligible = bool(
        not judge_errors
        and editor
        and editor.get("status") == "ok"
        and editor.get("decision") == "revise"
        and editor.get("corrected_zh")
        and editor.get("corrected_zh") != original
        and editor.get("confidence", 0.0) >= config.min_editor_confidence
        and not rescore_errors
        and all_rescorers_accept
        and final_score >= config.min_final_score
        and final_score - baseline_score >= config.min_improvement
    )

    status = "approved"
    if judge_errors or rescore_errors or (editor and editor.get("status") == "error"):
        status = "error"
    elif eligible:
        status = "corrected"
    elif issue_votes:
        status = "needs_review"

    return {
        "position": position,
        "segment_key": _segment_key(position, segment, config.signature(), context),
        "ja": str(segment.get("ja", "")),
        "original_zh": original,
        "final_zh": editor["corrected_zh"] if eligible else original,
        "status": status,
        "baseline_score": round(baseline_score, 2),
        "final_score": round(final_score, 2) if rescored else None,
        "issue_votes": issue_votes,
        "eligible_for_application": eligible,
        "judges": judges,
        "editor": editor,
        "rescore_judges": rescored,
    }


def _load_progress(path: Optional[Path]) -> dict[str, dict]:
    completed = {}
    if not path or not path.exists():
        return completed
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = item.get("segment_key")
            if not key:
                continue
            if item.get("status") == "error":
                completed.pop(key, None)
            else:
                completed[key] = item
    return completed


def _append_progress(path: Optional[Path], item: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(item, ensure_ascii=False) + "\n")
        file.flush()


def review_batch(
    segments: list[dict],
    config: MQMConfig,
    glossary: str,
    progress_path: str = "",
    completed_results: Optional[dict[str, dict]] = None,
    chat_fn: Callable = model_chat,
) -> list[dict]:
    config.validate()
    progress = Path(progress_path) if progress_path else None
    cached = _load_progress(progress)
    cached.update(completed_results or {})
    signature = config.signature()
    contexts = [
        _context(segments, position, config.context_window)
        for position in range(len(segments))
    ]
    results: list[Optional[dict]] = [None] * len(segments)
    pending = []
    for position, segment in enumerate(segments):
        key = _segment_key(position, segment, signature, contexts[position])
        if key in cached:
            results[position] = cached[key]
        else:
            pending.append(position)

    print(
        f"MQM reviewing {len(segments)} segments; resume={len(segments) - len(pending)}, "
        f"pending={len(pending)}, judges={','.join(config.judge_models)}"
    )
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        futures = {
            executor.submit(
                review_segment,
                position,
                segments[position],
                contexts[position],
                glossary,
                config,
                chat_fn,
            ): position
            for position in pending
        }
        for future in as_completed(futures):
            position = futures[future]
            item = future.result()
            results[position] = item
            _append_progress(progress, item)
            print(
                f"  [{position + 1}/{len(segments)}] {item['status']} "
                f"baseline={item['baseline_score']} final={item['final_score']}"
            )
    return [item for item in results if item is not None]


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def review_translation_file(
    input_path: str,
    output_path: str,
    report_path: str,
    *,
    progress_path: str = "",
    glossary_path: str = "",
    config: Optional[MQMConfig] = None,
    apply_fixes: bool = True,
    chat_fn: Callable = model_chat,
) -> dict:
    source = Path(input_path)
    segments = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(segments, list):
        raise ValueError("MQM input must be a JSON list")
    config = (config or MQMConfig()).validate()
    glossary = load_glossary_prompt(glossary_path)
    reviews = []
    completed_results = {}
    for pass_index in range(1, MAX_INCOMPLETE_PASSES + 1):
        reviews = review_batch(
            segments,
            config,
            glossary,
            progress_path,
            completed_results,
            chat_fn,
        )
        error_count = sum(item["status"] == "error" for item in reviews)
        completed_results.update(
            (item["segment_key"], item)
            for item in reviews
            if item["status"] != "error"
        )
        if error_count == 0:
            break
        if pass_index < MAX_INCOMPLETE_PASSES:
            print(
                f"Retrying {error_count} incomplete MQM review(s); "
                f"pass {pass_index + 1}/{MAX_INCOMPLETE_PASSES}"
            )

    output = []
    for segment, review in zip(segments, reviews):
        item = dict(segment)
        applied = bool(apply_fixes and review["eligible_for_application"])
        if applied:
            item["text"] = review["final_zh"]
        item["mqm_review"] = {
            "segment_key": review["segment_key"],
            "status": review["status"],
            "baseline_score": review["baseline_score"],
            "final_score": review["final_score"],
            "issue_votes": review["issue_votes"],
            "eligible_for_application": review["eligible_for_application"],
            "applied": applied,
            "original_zh": review["original_zh"],
            "final_zh": item.get("text", _segment_text(item)),
        }
        output.append(item)

    summary = {
        "total": len(reviews),
        "approved": sum(item["status"] == "approved" for item in reviews),
        "corrected": sum(item["status"] == "corrected" for item in reviews),
        "needs_review": sum(item["status"] == "needs_review" for item in reviews),
        "errors": sum(item["status"] == "error" for item in reviews),
        "eligible": sum(item["eligible_for_application"] for item in reviews),
        "applied": sum(
            apply_fixes and item["eligible_for_application"] for item in reviews
        ),
    }
    report = {
        "schema": "anime-accurate-sub/gemba-mqm-quality-v1",
        "source": str(source.resolve()),
        "config": asdict(config),
        "config_signature": config.signature(),
        "apply_fixes": apply_fixes,
        "summary": summary,
        "reviews": reviews,
    }
    _atomic_json(Path(output_path), output)
    _atomic_json(Path(report_path), report)
    if summary["errors"]:
        raise RuntimeError(
            f"MQM review has {summary['errors']} incomplete segment(s); "
            "rerun with the same progress path"
        )
    return report


def _load_config(path: str) -> MQMConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    return MQMConfig.from_dict(data).validate()


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditable dual-judge GEMBA-MQM gate")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="mqm_reviewed.json")
    parser.add_argument("--report", default="mqm_quality_report.json")
    parser.add_argument("--progress", default="")
    parser.add_argument("--glossary", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = review_translation_file(
        args.input,
        args.output,
        args.report,
        progress_path=args.progress,
        glossary_path=args.glossary,
        config=_load_config(args.config),
        apply_fixes=not args.dry_run,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
