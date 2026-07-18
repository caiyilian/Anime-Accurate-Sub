"""S11.2: auditable multi-agent subtitle review.

Five reviewer prompts inspect one translated segment in parallel.  A separate
editor may replace the translation only when multiple reviewers agree and the
editor returns a high-confidence, strictly structured decision.  The module is
safe to resume on a season-sized job and never mutates the source file.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional


DEFAULT_MODEL = "EasonONLINE/Sakura-qwen2.5-v1.0:7b"
DEFAULT_SENSENOVA_URL = "https://token.sensenova.cn/v1"
VALID_VERDICTS = {"ok", "fix", "suspicious"}
VALID_EDITOR_DECISIONS = {"keep", "replace"}
MAX_INCOMPLETE_PASSES = 3
AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": sorted(VALID_VERDICTS)},
        "suggested_zh": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["verdict", "suggested_zh", "reason", "confidence"],
    "additionalProperties": False,
}
EDITOR_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": sorted(VALID_EDITOR_DECISIONS)},
        "corrected_zh": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["decision", "corrected_zh", "reason", "confidence"],
    "additionalProperties": False,
}


AGENTS = {
    "consistency": {
        "name": "Consistency Checker",
        "focus": "角色名、称呼、术语和前后台词是否一致",
    },
    "naturalness": {
        "name": "Naturalness Checker",
        "focus": "中文是否自然、简洁、符合口语和字幕阅读习惯",
    },
    "accuracy": {
        "name": "Accuracy Checker",
        "focus": "中文是否忠实表达日文含义、语气、主客体，是否漏译或增译",
    },
    "asr_check": {
        "name": "ASR Quality Checker",
        "focus": "日文 ASR 是否存在误听、断裂、重复或与上下文矛盾",
    },
    "style": {
        "name": "Anime Style Checker",
        "focus": "译文是否符合轻松动漫对白的语气、人物关系和场景情绪",
    },
}


@dataclass
class ReviewConfig:
    provider: str = field(
        default_factory=lambda: os.environ.get("REVIEW_PROVIDER", "ollama")
    )
    host: str = field(
        default_factory=lambda: os.environ.get(
            "REVIEW_HOST", os.environ.get("OLLAMA_HOST", "localhost")
        )
    )
    review_model: str = field(
        default_factory=lambda: os.environ.get("REVIEW_MODEL", DEFAULT_MODEL)
    )
    base_url: str = field(
        default_factory=lambda: os.environ.get("REVIEW_BASE_URL", "")
    )
    api_key_file: str = field(
        default_factory=lambda: os.environ.get("REVIEW_API_KEY_FILE", "")
    )
    editor_provider: str = field(
        default_factory=lambda: os.environ.get("EDITOR_PROVIDER", "")
    )
    editor_host: str = field(
        default_factory=lambda: os.environ.get(
            "EDITOR_HOST",
            os.environ.get("REVIEW_HOST", os.environ.get("OLLAMA_HOST", "localhost")),
        )
    )
    editor_model: str = field(
        default_factory=lambda: os.environ.get(
            "EDITOR_MODEL", os.environ.get("REVIEW_MODEL", DEFAULT_MODEL)
        )
    )
    editor_base_url: str = field(
        default_factory=lambda: os.environ.get("EDITOR_BASE_URL", "")
    )
    editor_api_key_file: str = field(
        default_factory=lambda: os.environ.get("EDITOR_API_KEY_FILE", "")
    )
    agent_models: dict[str, str] = field(default_factory=dict)
    max_workers: int = 2
    context_window: int = 3
    min_fix_votes: int = 2
    min_reviewer_confidence: float = 0.75
    min_editor_confidence: float = 0.80
    retries: int = 3
    timeout_s: int = 300

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ReviewConfig":
        if not data:
            return cls()
        known = {item.name for item in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in known})

    def validate(self) -> "ReviewConfig":
        self.provider = self.provider.strip().lower()
        if self.provider not in {"ollama", "openai"}:
            raise ValueError("provider must be ollama or openai")
        self.editor_provider = (self.editor_provider or self.provider).strip().lower()
        if self.editor_provider not in {"ollama", "openai"}:
            raise ValueError("editor_provider must be ollama or openai")
        if self.provider == "openai" and not (self.api_key_file or os.environ.get("REVIEW_API_KEY")):
            raise ValueError("openai review provider requires api_key_file or REVIEW_API_KEY")
        if self.editor_provider == "openai":
            self.editor_base_url = self.editor_base_url or self.base_url
            self.editor_api_key_file = self.editor_api_key_file or self.api_key_file
        if self.max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if self.context_window < 0:
            raise ValueError("context_window must be >= 0")
        if not 1 <= self.min_fix_votes <= len(AGENTS):
            raise ValueError(f"min_fix_votes must be between 1 and {len(AGENTS)}")
        if not 0 <= self.min_reviewer_confidence <= 1:
            raise ValueError("min_reviewer_confidence must be between 0 and 1")
        if not 0 <= self.min_editor_confidence <= 1:
            raise ValueError("min_editor_confidence must be between 0 and 1")
        if self.retries < 1:
            raise ValueError("retries must be >= 1")
        return self


def _api_url(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    authority = host.split("//", 1)[1].split("/", 1)[0]
    if ":" not in authority:
        host = f"{host}:11434"
    if host.endswith("/api"):
        return host
    return f"{host}/api"


def ollama_chat(
    messages: list[dict],
    *,
    temperature: float = 0.1,
    model: str = DEFAULT_MODEL,
    host: str = "localhost",
    json_mode: bool = True,
    json_schema: Optional[dict] = None,
    timeout_s: int = 300,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 768},
    }
    if json_mode:
        payload["format"] = json_schema or "json"
    request = urllib.request.Request(
        f"{_api_url(host)}/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result.get("message", {}).get("content", "").strip()


_KEY_SEQUENCE = itertools.count()
_KEY_LOCK = threading.Lock()


def _api_keys(path: str, environment_name: str = "REVIEW_API_KEY") -> list[str]:
    keys = []
    environment_value = os.environ.get(environment_name, "").strip()
    if environment_value:
        keys.append(environment_value)
    if path:
        keys.extend(
            line.strip()
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    # Preserve order while removing accidental duplicates.
    return list(dict.fromkeys(keys))


def _next_api_key(path: str) -> str:
    keys = _api_keys(path)
    if not keys:
        raise ValueError("no API key is available")
    with _KEY_LOCK:
        position = next(_KEY_SEQUENCE)
    return keys[position % len(keys)]


def openai_chat(
    messages: list[dict],
    *,
    temperature: float = 0.1,
    model: str,
    base_url: str,
    api_key_file: str,
    json_mode: bool = True,
    timeout_s: int = 300,
    **_kwargs,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": 2048,
    }
    if json_mode:
        # SenseNova's OpenAI-compatible gateway supports json_object.  The
        # semantic schema remains in the prompt and is validated locally.
        payload["response_format"] = {"type": "json_object"}
    endpoint = (base_url or DEFAULT_SENSENOVA_URL).rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_next_api_key(api_key_file)}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # Do not include response bodies: providers sometimes echo request
        # metadata, and review logs must never risk persisting credentials.
        raise RuntimeError(f"OpenAI-compatible API returned HTTP {error.code}") from error
    choices = result.get("choices") or []
    if not choices:
        raise ValueError("OpenAI-compatible API response has no choices")
    return str(choices[0].get("message", {}).get("content", "")).strip()


def model_chat(
    messages: list[dict],
    *,
    provider: str = "ollama",
    base_url: str = "",
    api_key_file: str = "",
    **kwargs,
) -> str:
    if provider == "openai":
        return openai_chat(
            messages,
            base_url=base_url,
            api_key_file=api_key_file,
            **kwargs,
        )
    return ollama_chat(messages, **kwargs)


def _json_object(response: str) -> tuple[dict, bool]:
    """Parse one JSON object with only deterministic syntax repairs.

    Sakura occasionally stops after a complete final value but before the
    closing brace.  Appending that single brace (or removing a trailing comma)
    cannot invent a verdict; all semantic fields are still schema-validated by
    the caller.  Natural-language keyword guessing remains deliberately banned.
    """
    text = (response or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    repaired = False
    try:
        value = json.loads(text)
    except json.JSONDecodeError as original_error:
        candidates = []
        without_trailing_comma = re.sub(r",\s*}$", "}", text)
        if without_trailing_comma != text:
            candidates.append(without_trailing_comma)
        if (
            text.startswith("{")
            and text.count("{") == text.count("}") + 1
            and len(re.findall(r'(?<!\\)"', text)) % 2 == 0
        ):
            candidates.append(text + "}")
        value = None
        for candidate in candidates:
            try:
                value = json.loads(candidate)
                repaired = True
                break
            except json.JSONDecodeError:
                continue
        if value is None:
            raise ValueError(
                f"response is not a JSON object: {original_error.msg}"
            ) from original_error
    if not isinstance(value, dict):
        raise ValueError("response JSON must be an object")
    return value, repaired


def _strict_object(value: dict, required: set[str], label: str) -> None:
    keys = set(value)
    missing = required - keys
    extra = keys - required
    if missing:
        raise ValueError(f"{label} response is missing fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"{label} response has unexpected fields: {sorted(extra)}")


def _strict_confidence(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} confidence must be a JSON number")
    confidence = float(value)
    if not 0 <= confidence <= 1:
        raise ValueError(f"{label} confidence must be between 0 and 1")
    return confidence


def parse_agent_response(response: str) -> dict:
    value, repaired = _json_object(response)
    _strict_object(
        value, {"verdict", "suggested_zh", "reason", "confidence"}, "reviewer"
    )
    if not all(isinstance(value[key], str) for key in ("verdict", "suggested_zh", "reason")):
        raise ValueError("reviewer verdict, suggested_zh and reason must be strings")
    verdict = str(value.get("verdict", "")).strip().lower()
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"invalid reviewer verdict: {verdict!r}")
    suggested = str(value.get("suggested_zh") or "").strip()
    if verdict == "fix" and not suggested:
        raise ValueError("fix verdict requires suggested_zh")
    return {
        "verdict": verdict,
        "suggested_zh": suggested or None,
        "reason": str(value.get("reason") or "").strip(),
        "confidence": _strict_confidence(value["confidence"], "reviewer"),
        "response_repaired": repaired,
    }


def parse_editor_response(response: str) -> dict:
    value, repaired = _json_object(response)
    _strict_object(
        value, {"decision", "corrected_zh", "reason", "confidence"}, "editor"
    )
    if not all(isinstance(value[key], str) for key in ("decision", "corrected_zh", "reason")):
        raise ValueError("editor decision, corrected_zh and reason must be strings")
    decision = str(value.get("decision", "")).strip().lower()
    if decision not in VALID_EDITOR_DECISIONS:
        raise ValueError(f"invalid editor decision: {decision!r}")
    corrected = str(value.get("corrected_zh") or "").strip()
    if decision == "replace" and not corrected:
        raise ValueError("replace decision requires corrected_zh")
    return {
        "decision": decision,
        "corrected_zh": corrected or None,
        "reason": str(value.get("reason") or "").strip(),
        "confidence": _strict_confidence(value["confidence"], "editor"),
        "response_repaired": repaired,
    }


def _segment_text(segment: dict) -> str:
    return str(segment.get("text", segment.get("zh", ""))).strip()


def _segment_key(position: int, segment: dict) -> str:
    payload = {
        "position": position,
        "id": segment.get("id", segment.get("index")),
        "ja": str(segment.get("ja", "")),
        "text": _segment_text(segment),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"{position}:{digest}"


def _context_for(segments: list[dict], position: int, window: int) -> str:
    start = max(0, position - window)
    end = min(len(segments), position + window + 1)
    lines = []
    for index in range(start, end):
        marker = "目标" if index == position else "上下文"
        segment = segments[index]
        lines.append(
            f"[{marker} {index}] 日文：{segment.get('ja', '')}\n"
            f"[{marker} {index}] 中文：{_segment_text(segment)}"
        )
    return "\n".join(lines)


def load_glossary_prompt(path: str = "") -> str:
    if not path:
        return "（未提供术语表）"
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    terms = value.get("terms", value) if isinstance(value, dict) else value
    rows = []
    if isinstance(terms, list):
        for item in terms:
            if isinstance(item, dict) and item.get("ja") and item.get("zh"):
                rows.append(f"{item['ja']} => {item['zh']}")
    elif isinstance(terms, dict):
        rows.extend(f"{ja} => {zh}" for ja, zh in terms.items())
    return "\n".join(rows) if rows else "（术语表为空）"


def _call_json_with_retries(
    messages: list[dict],
    *,
    model: str,
    host: str,
    provider: str,
    base_url: str,
    api_key_file: str,
    config: ReviewConfig,
    parser: Callable[[str], dict],
    json_schema: dict,
    chat_fn: Callable = model_chat,
    temperature: float = 0.1,
) -> tuple[Optional[dict], str, str, int, float]:
    last_response = ""
    last_error = ""
    started = time.time()
    for attempt in range(1, config.retries + 1):
        try:
            last_response = chat_fn(
                messages,
                temperature=temperature,
                model=model,
                host=host,
                provider=provider,
                base_url=base_url,
                api_key_file=api_key_file,
                json_mode=True,
                json_schema=json_schema,
                timeout_s=config.timeout_s,
            )
            return parser(last_response), last_response, "", attempt, time.time() - started
        except Exception as error:  # network and model-format failures are retryable
            last_error = str(error)
            if attempt < config.retries:
                time.sleep(min(2 ** (attempt - 1), 4))
    return None, last_response, last_error, config.retries, time.time() - started


def run_agent(
    agent_id: str,
    segment: dict,
    context: str,
    glossary: str,
    config: ReviewConfig,
    chat_fn: Callable = model_chat,
) -> dict:
    agent = AGENTS[agent_id]
    ja = str(segment.get("ja", "")).strip()
    zh = _segment_text(segment)
    system = (
        f"你是{agent['name']}，只负责检查：{agent['focus']}。"
        "不要为了追求不同而改写正确译文。只能输出一个 JSON 对象，不要复述提示词。"
    )
    prompt = f"""请审查目标字幕。

上下文：
{context}

目标日文：{ja}
目标中文：{zh}

必须遵守的术语：
{glossary}

只输出：
{{"verdict":"ok|fix|suspicious","suggested_zh":"完整建议译文，ok 时为空字符串","reason":"简短依据","confidence":0.0}}
confidence 范围为 0 到 1。ASR 可疑用 suspicious；翻译确有错误才用 fix。"""
    model = config.agent_models.get(agent_id, config.review_model)
    parsed, raw, error, attempts, elapsed = _call_json_with_retries(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        model=model,
        host=config.host,
        provider=config.provider,
        base_url=config.base_url,
        api_key_file=config.api_key_file,
        config=config,
        parser=parse_agent_response,
        json_schema=AGENT_SCHEMA,
        chat_fn=chat_fn,
    )
    result = {
        "agent": agent_id,
        "agent_name": agent["name"],
        "model": model,
        "attempts": attempts,
        "time_s": round(elapsed, 2),
        "raw_response": raw,
    }
    if parsed is None:
        result.update(
            verdict="error", suggested_zh=None, reason=error,
            confidence=0.0, error=error,
        )
    else:
        result.update(parsed)
    return result


def run_editor(
    segment: dict,
    context: str,
    glossary: str,
    agent_results: dict[str, dict],
    config: ReviewConfig,
    chat_fn: Callable = model_chat,
) -> dict:
    feedback = [
        {
            "agent": agent_id,
            "verdict": result.get("verdict"),
            "suggested_zh": result.get("suggested_zh"),
            "reason": result.get("reason"),
            "confidence": result.get("confidence"),
        }
        for agent_id in AGENTS
        for result in [agent_results[agent_id]]
    ]
    system = (
        "你是保守的字幕总编。只有审查意见揭示真实语义、术语、ASR 或中文表达问题时才替换；"
        "意见冲突、证据不足或只是同义改写时必须保留原译。只能输出一个 JSON 对象。"
    )
    prompt = f"""上下文：
{context}

目标日文：{segment.get('ja', '')}
原中文：{_segment_text(segment)}

术语：
{glossary}

审查意见：
{json.dumps(feedback, ensure_ascii=False)}

只输出：
{{"decision":"keep|replace","corrected_zh":"完整最终译文，keep 时可为空","reason":"依据","confidence":0.0}}"""
    parsed, raw, error, attempts, elapsed = _call_json_with_retries(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        model=config.editor_model,
        host=config.editor_host,
        provider=config.editor_provider,
        base_url=config.editor_base_url,
        api_key_file=config.editor_api_key_file,
        config=config,
        parser=parse_editor_response,
        json_schema=EDITOR_SCHEMA,
        chat_fn=chat_fn,
        temperature=0.05,
    )
    result = {
        "model": config.editor_model,
        "attempts": attempts,
        "time_s": round(elapsed, 2),
        "raw_response": raw,
    }
    if parsed is None:
        result.update(
            decision="error", corrected_zh=None, reason=error,
            confidence=0.0, error=error,
        )
    else:
        result.update(parsed)
    return result


def review_segment(
    position: int,
    segment: dict,
    context: str,
    glossary: str,
    config: ReviewConfig,
    chat_fn: Callable = model_chat,
) -> dict:
    results = {}
    with ThreadPoolExecutor(max_workers=len(AGENTS)) as executor:
        futures = {
            executor.submit(
                run_agent, agent_id, segment, context, glossary, config, chat_fn
            ): agent_id
            for agent_id in AGENTS
        }
        for future in as_completed(futures):
            agent_id = futures[future]
            try:
                results[agent_id] = future.result()
            except Exception as error:
                results[agent_id] = {
                    "agent": agent_id,
                    "agent_name": AGENTS[agent_id]["name"],
                    "verdict": "error",
                    "reason": str(error),
                    "confidence": 0.0,
                    "suggested_zh": None,
                }

    results = {agent_id: results[agent_id] for agent_id in AGENTS}
    fix_votes = sum(
        result.get("verdict") in {"fix", "suspicious"}
        and result.get("confidence", 0.0) >= config.min_reviewer_confidence
        for result in results.values()
    )
    editor = None
    if fix_votes >= config.min_fix_votes:
        editor = run_editor(segment, context, glossary, results, config, chat_fn)

    original = _segment_text(segment)
    errors = sum(result.get("verdict") == "error" for result in results.values())
    editor_error = bool(editor and editor.get("decision") == "error")
    applied = bool(
        editor
        and errors == 0
        and not editor_error
        and editor.get("decision") == "replace"
        and editor.get("corrected_zh")
        and editor.get("corrected_zh") != original
        and editor.get("confidence", 0.0) >= config.min_editor_confidence
    )
    status = "corrected" if applied else "approved"
    if errors or editor_error:
        status = "error"
    elif fix_votes and not applied:
        status = "needs_review"

    return {
        "position": position,
        "segment_key": _segment_key(position, segment),
        "ja": str(segment.get("ja", "")),
        "original_zh": original,
        "final_zh": editor["corrected_zh"] if applied else original,
        "status": status,
        "fix_votes": fix_votes,
        "applied": applied,
        "agent_results": results,
        "editor_result": editor,
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
            editor_result = item.get("editor_result") or {}
            if (
                item.get("status") == "error"
                or editor_result.get("decision") == "error"
            ):
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
    max_workers: Optional[int] = None,
    *,
    config: Optional[ReviewConfig] = None,
    glossary: str = "（未提供术语表）",
    progress_path: str = "",
    completed_results: Optional[dict[str, dict]] = None,
    chat_fn: Callable = model_chat,
) -> list[dict]:
    config = config or ReviewConfig()
    if max_workers is not None:
        config.max_workers = max_workers
    config.validate()
    progress = Path(progress_path) if progress_path else None
    cached = _load_progress(progress)
    cached.update(completed_results or {})
    results: list[Optional[dict]] = [None] * len(segments)
    pending = []
    for position, segment in enumerate(segments):
        key = _segment_key(position, segment)
        if key in cached:
            results[position] = cached[key]
        else:
            pending.append(position)

    print(
        f"Reviewing {len(segments)} segments with {len(AGENTS)} agents; "
        f"resume={len(segments) - len(pending)}, pending={len(pending)}"
    )
    print(f"Reviewer model: {config.review_model}; editor: {config.editor_model}")

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        futures = {
            executor.submit(
                review_segment,
                position,
                segments[position],
                _context_for(segments, position, config.context_window),
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
                f"votes={item['fix_votes']}"
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
    reviewed_path: str,
    report_path: str,
    *,
    progress_path: str = "",
    glossary_path: str = "",
    config: Optional[ReviewConfig] = None,
    apply_fixes: bool = True,
    chat_fn: Callable = model_chat,
) -> dict:
    source = Path(input_path)
    segments = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(segments, list):
        raise ValueError("translated input must be a JSON list")
    config = (config or ReviewConfig()).validate()
    glossary = load_glossary_prompt(glossary_path)
    reviews = []
    completed_results = {}
    for pass_index in range(1, MAX_INCOMPLETE_PASSES + 1):
        reviews = review_batch(
            segments,
            config=config,
            glossary=glossary,
            progress_path=progress_path,
            completed_results=completed_results,
            chat_fn=chat_fn,
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
                f"Retrying {error_count} incomplete multi-agent review(s); "
                f"pass {pass_index + 1}/{MAX_INCOMPLETE_PASSES}"
            )

    reviewed_segments = []
    for segment, review in zip(segments, reviews):
        output = dict(segment)
        if apply_fixes and review["applied"]:
            output["text"] = review["final_zh"]
        output["multi_agent_review"] = {
            "segment_key": review["segment_key"],
            "status": review["status"],
            "fix_votes": review["fix_votes"],
            "applied": bool(apply_fixes and review["applied"]),
            "original_zh": review["original_zh"],
            "final_zh": output.get("text", _segment_text(output)),
            "editor": review.get("editor_result"),
        }
        reviewed_segments.append(output)

    summary = {
        "total": len(reviews),
        "approved": sum(item["status"] == "approved" for item in reviews),
        "corrected": sum(item["status"] == "corrected" for item in reviews),
        "needs_review": sum(item["status"] == "needs_review" for item in reviews),
        "errors": sum(item["status"] == "error" for item in reviews),
        "applied": sum(bool(apply_fixes and item["applied"]) for item in reviews),
    }
    report = {
        "schema": "anime-accurate-sub/multi-agent-review-v2",
        "source": str(source.resolve()),
        "config": asdict(config),
        "apply_fixes": apply_fixes,
        "summary": summary,
        "reviews": reviews,
    }
    _atomic_json(Path(reviewed_path), reviewed_segments)
    _atomic_json(Path(report_path), report)
    if summary["errors"]:
        raise RuntimeError(
            f"multi-agent review has {summary['errors']} incomplete segment(s); "
            "rerun with the same progress path"
        )
    return report


def create_test_segments() -> list[dict]:
    return [
        {"ja": "おはよう、唯", "text": "早安，唯"},
        {"ja": "今日も元気だね", "text": "今天也很有精神呢"},
        {"ja": "澪ちゃん、一緒に練習しない？", "text": "澪，要不要一起练习？"},
        {"ja": "ありがとう、唯。じゃあ放課後ね", "text": "谢谢你，唯。那放学后见"},
    ]


def evaluate() -> None:
    output_root = Path(__file__).resolve().parent.parent / "docs" / "evaluation"
    source = output_root / "S11.2_test_segments.json"
    reviewed = output_root / "S11.2_reviewed_segments.json"
    report = output_root / "S11.2_review_results.json"
    _atomic_json(source, create_test_segments())
    result = review_translation_file(
        str(source), str(reviewed), str(report), apply_fixes=True
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


def _load_config(path: str, args) -> ReviewConfig:
    data = {}
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    overrides = {
        "provider": args.provider,
        "host": args.host,
        "review_model": args.model,
        "base_url": args.base_url,
        "api_key_file": args.api_key_file,
        "editor_provider": args.editor_provider,
        "editor_host": args.editor_host,
        "editor_model": args.editor_model,
        "editor_base_url": args.editor_base_url,
        "editor_api_key_file": args.editor_api_key_file,
        "max_workers": args.workers,
        "min_fix_votes": args.min_fix_votes,
        "min_reviewer_confidence": args.min_reviewer_confidence,
        "min_editor_confidence": args.min_editor_confidence,
        "context_window": args.context_window,
    }
    data.update({key: value for key, value in overrides.items() if value is not None})
    return ReviewConfig.from_dict(data).validate()


def main() -> None:
    parser = argparse.ArgumentParser(description="S11.2 auditable multi-agent review")
    parser.add_argument("--input", help="translated JSON list")
    parser.add_argument("--output", default="reviewed.json", help="reviewed JSON")
    parser.add_argument("--report", default="multi_agent_review.json")
    parser.add_argument("--progress", default="", help="resumable JSONL progress")
    parser.add_argument("--glossary", default="")
    parser.add_argument("--config", default="", help="review configuration JSON")
    parser.add_argument("--host")
    parser.add_argument("--model")
    parser.add_argument("--provider", choices=("ollama", "openai"))
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-file")
    parser.add_argument("--editor-host")
    parser.add_argument("--editor-model")
    parser.add_argument("--editor-provider", choices=("ollama", "openai"))
    parser.add_argument("--editor-base-url")
    parser.add_argument("--editor-api-key-file")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--min-fix-votes", type=int)
    parser.add_argument("--min-reviewer-confidence", type=float)
    parser.add_argument("--min-editor-confidence", type=float)
    parser.add_argument("--context-window", type=int)
    parser.add_argument(
        "--dry-run", action="store_true", help="review but do not apply corrections"
    )
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return
    if not args.input:
        parser.error("--input is required unless --evaluate is used")
    result = review_translation_file(
        args.input,
        args.output,
        args.report,
        progress_path=args.progress,
        glossary_path=args.glossary,
        config=_load_config(args.config, args),
        apply_fixes=not args.dry_run,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
