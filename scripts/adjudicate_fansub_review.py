"""Final subtitle adjudication with fansub, context, and independent model evidence.

The command is intentionally report-first.  It can resume expensive model calls
from JSONL progress, while applying changes requires an explicit ``--apply``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval_fansub_quality import (  # noqa: E402
    Segment,
    align_segments,
    clean_subtitle_text,
    load_fansub,
)
from scripts.review_agents import model_chat  # noqa: E402

VALID_DECISIONS = {"keep", "revise"}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _case_id(episode: int, index: int, ja: str, zh: str) -> str:
    digest = hashlib.sha256(f"{episode}\0{index}\0{ja}\0{zh}".encode()).hexdigest()[:16]
    return f"E{episode:02d}:{index}:{digest}"


def _episode_directories(root: Path) -> list[tuple[int, Path]]:
    result = []
    for path in root.iterdir():
        if not path.is_dir() or "第" not in path.name or "集" not in path.name:
            continue
        try:
            number = int(path.name.split("第", 1)[1].split("集", 1)[0])
        except (IndexError, ValueError):
            continue
        result.append((number, path))
    return sorted(result)


def _prediction_segments(items: list[dict[str, Any]]) -> list[Segment]:
    return [
        Segment(
            start=float(item.get("start", 0.0)),
            end=float(item.get("end", item.get("start", 0.0))),
            text=clean_subtitle_text(str(item.get("text", ""))),
            source=clean_subtitle_text(str(item.get("ja", ""))),
        )
        for item in items
    ]


def _compact_mqm_evidence(review: dict[str, Any] | None) -> dict[str, Any]:
    if not review:
        return {}
    judges = []
    for judge in review.get("judges", []):
        judges.append(
            {
                "model": judge.get("model"),
                "recommendation": judge.get("recommendation"),
                "suggested_zh": judge.get("suggested_zh"),
                "confidence": judge.get("confidence"),
                "overall": judge.get("overall"),
                "errors": judge.get("errors", []),
                "dimensions": judge.get("dimensions", {}),
            }
        )
    editor = review.get("editor") or {}
    return {
        "status": review.get("status"),
        "baseline_score": review.get("baseline_score"),
        "judges": judges,
        "editor": {
            "decision": editor.get("decision"),
            "corrected_zh": editor.get("corrected_zh"),
            "reason": editor.get("reason"),
            "confidence": editor.get("confidence"),
        },
    }


def collect_cases(
    prediction_root: Path,
    reference_root: Path,
    *,
    context_window: int = 5,
    approved_sample_per_episode: int = 0,
) -> list[dict[str, Any]]:
    """Collect all MQM needs-review rows plus deterministic low-similarity samples."""
    cases = []
    for episode, episode_dir in _episode_directories(prediction_root):
        reviewed_path = episode_dir / "mqm_reviewed.json"
        report_path = episode_dir / "mqm_quality_report.json"
        reference_path = reference_root / f"K-ON! 2009 - EP{episode:02d}.ass"
        if not reviewed_path.exists() or not report_path.exists() or not reference_path.exists():
            continue

        items = _read_json(reviewed_path)
        report = _read_json(report_path)
        evidence_by_key = {
            review.get("segment_key"): review for review in report.get("reviews", [])
        }
        predictions = _prediction_segments(items)
        references = load_fansub(reference_path)
        alignments, _ = align_segments(predictions, references)
        alignment_by_index = {item.prediction_index: item for item in alignments}

        mandatory = []
        approved = []
        for index, item in enumerate(items):
            mqm = item.get("mqm_review") or {}
            status = mqm.get("status", "")
            alignment = alignment_by_index.get(index)
            if status == "needs_review":
                mandatory.append(index)
            elif status == "approved" and alignment is not None:
                approved.append((alignment.chrf, index))

        sampled = {
            index
            for _, index in sorted(approved)[: max(0, approved_sample_per_episode)]
        }
        for index in mandatory + sorted(sampled):
            item = items[index]
            mqm = item.get("mqm_review") or {}
            alignment = alignment_by_index.get(index)
            before = items[max(0, index - context_window):index]
            after = items[index + 1:index + 1 + context_window]
            cases.append(
                {
                    "case_id": _case_id(
                        episode,
                        index,
                        str(item.get("ja", "")),
                        str(item.get("text", "")),
                    ),
                    "episode": episode,
                    "episode_dir": str(episode_dir),
                    "index": index,
                    "selection": "needs_review" if index in mandatory else "approved_sample",
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "ja": item.get("ja", ""),
                    "current_zh": item.get("text", ""),
                    "context_before": [
                        {"ja": row.get("ja", ""), "zh": row.get("text", "")}
                        for row in before
                    ],
                    "context_after": [
                        {"ja": row.get("ja", ""), "zh": row.get("text", "")}
                        for row in after
                    ],
                    "fansub_reference": alignment.reference if alignment else "",
                    "fansub_alignment": {
                        "reference_indices": list(alignment.reference_indices)
                        if alignment
                        else [],
                        "char_f1": alignment.char_f1 if alignment else 0.0,
                        "chrf": alignment.chrf if alignment else 0.0,
                        "edit_similarity": alignment.edit_similarity if alignment else 0.0,
                    },
                    "mqm_evidence": _compact_mqm_evidence(
                        evidence_by_key.get(mqm.get("segment_key"))
                    ),
                }
            )
    return cases


def _json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Model response must be a JSON object")
    return value


def _parse_decision(raw: str) -> dict[str, Any]:
    value = _json_object(raw)
    decision = str(value.get("decision", "")).strip().lower()
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Invalid decision: {decision!r}")
    corrected = str(value.get("corrected_zh") or "").strip()
    if decision == "revise" and not corrected:
        raise ValueError("revise requires corrected_zh")
    confidence = float(value.get("confidence", 0.0))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return {
        "decision": decision,
        "corrected_zh": corrected if decision == "revise" else "",
        "severity": str(value.get("severity", "none")),
        "reason": str(value.get("reason", "")).strip(),
        "confidence": confidence,
        "reference_reliability": str(value.get("reference_reliability", "unknown")),
    }


def _call_decision(
    messages: list[dict[str, str]],
    *,
    model: str,
    fallback_model: str,
    config: dict[str, Any],
    chat_fn: Callable[..., str] = model_chat,
) -> dict[str, Any]:
    errors = []
    models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
    attempts = max(1, int(config.get("retries", 3)))
    started = time.monotonic()
    for candidate in models:
        for attempt in range(1, attempts + 1):
            try:
                raw = chat_fn(
                    messages,
                    provider=config.get("provider", "openai"),
                    base_url=config.get("base_url", ""),
                    api_key_file=config.get("api_key_file", ""),
                    model=candidate,
                    json_mode=True,
                    temperature=0.1,
                    timeout_s=int(config.get("timeout_s", 600)),
                )
                parsed = _parse_decision(raw)
                parsed.update(
                    {
                        "model": candidate,
                        "primary_model": model,
                        "fallback_used": candidate != model,
                        "attempt": attempt,
                        "time_s": round(time.monotonic() - started, 2),
                    }
                )
                return parsed
            except Exception as error:  # network and strict schema failures retry alike
                errors.append(f"{candidate} attempt {attempt}: {error}")
    raise RuntimeError("; ".join(errors))


def _review_messages(case: dict[str, Any]) -> list[dict[str, str]]:
    payload = {
        key: case[key]
        for key in (
            "episode",
            "index",
            "start",
            "end",
            "ja",
            "current_zh",
            "context_before",
            "context_after",
            "fansub_reference",
            "fansub_alignment",
            "mqm_evidence",
        )
    }
    return [
        {
            "role": "system",
            "content": (
                "你是日语动画字幕终审。逐字理解日文，并结合前后文判断当前简体中文是否准确、"
                "自然、符合人物语气。字幕组参考译文只是独立证据，可能存在一拆多、多合一、"
                "意译或时间轴轻微偏差，禁止不加判断地照抄。既不要为了不同措辞而改写，也不能"
                "放过漏译、错译、指代错误、人物关系错误或不自然中文。只输出 JSON："
                '{"decision":"keep|revise","corrected_zh":"",'
                '"severity":"none|minor|major","reason":"中文理由",'
                '"confidence":0.0,"reference_reliability":"high|medium|low"}'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]


def _adjudicator_messages(
    case: dict[str, Any], reviews: list[dict[str, Any]]
) -> list[dict[str, str]]:
    payload = {
        "case": {
            key: case[key]
            for key in (
                "episode",
                "index",
                "ja",
                "current_zh",
                "context_before",
                "context_after",
                "fansub_reference",
                "fansub_alignment",
                "mqm_evidence",
            )
        },
        "independent_reviews": reviews,
    }
    return [
        {
            "role": "system",
            "content": (
                "你是最终裁决编辑。重新独立核对日文、上下文、当前译文、字幕组参考和两份审查，"
                "解决审查分歧。参考字幕不是绝对标准；只有当前译文确有准确性、流畅性、术语或"
                "人物语气问题时才 revise。修订必须是一行可直接发布的简体中文字幕。只输出 JSON："
                '{"decision":"keep|revise","corrected_zh":"",'
                '"severity":"none|minor|major","reason":"中文理由",'
                '"confidence":0.0,"reference_reliability":"high|medium|low"}'
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def adjudicate_case(
    case: dict[str, Any],
    config: dict[str, Any],
    *,
    chat_fn: Callable[..., str] = model_chat,
) -> dict[str, Any]:
    reviews = []
    fallbacks = config.get("review_fallback_models", {})
    for model in config.get("review_models", []):
        reviews.append(
            _call_decision(
                _review_messages(case),
                model=model,
                fallback_model=str(fallbacks.get(model, "")),
                config=config,
                chat_fn=chat_fn,
            )
        )
    final = _call_decision(
        _adjudicator_messages(case, reviews),
        model=str(config["adjudicator_model"]),
        fallback_model=str(config.get("adjudicator_fallback_model", "")),
        config=config,
        chat_fn=chat_fn,
    )
    return {
        "case_id": case["case_id"],
        "status": "ok",
        "selection": case["selection"],
        "episode": case["episode"],
        "index": case["index"],
        "ja": case["ja"],
        "current_zh": case["current_zh"],
        "fansub_reference": case["fansub_reference"],
        "reviews": reviews,
        "adjudication": final,
    }


def _load_progress(path: Path) -> dict[str, dict[str, Any]]:
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("status") == "ok" and item.get("case_id"):
            result[item["case_id"]] = item
    return result


def run_adjudication(
    cases: list[dict[str, Any]],
    config: dict[str, Any],
    progress_path: Path,
    *,
    chat_fn: Callable[..., str] = model_chat,
) -> list[dict[str, Any]]:
    completed = _load_progress(progress_path)
    pending = [case for case in cases if case["case_id"] not in completed]
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(cases)
    done = len(completed)
    print(f"Final adjudication: {done}/{total} resumed, {len(pending)} pending")

    def work(case: dict[str, Any]) -> dict[str, Any]:
        try:
            return adjudicate_case(case, config, chat_fn=chat_fn)
        except Exception as error:
            return {
                "case_id": case["case_id"],
                "status": "error",
                "episode": case["episode"],
                "index": case["index"],
                "error": str(error)[:2000],
            }

    with progress_path.open("a", encoding="utf-8") as stream:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, int(config.get("max_workers", 4)))
        ) as executor:
            futures = {executor.submit(work, case): case for case in pending}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                stream.write(json.dumps(result, ensure_ascii=False) + "\n")
                stream.flush()
                if result.get("status") == "ok":
                    completed[result["case_id"]] = result
                done += 1
                print(f"  Reviewed: {done}/{total} ({result.get('status')})", flush=True)
    return [completed[case["case_id"]] for case in cases if case["case_id"] in completed]


def build_report(
    cases: list[dict[str, Any]], results: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    result_by_id = {item["case_id"]: item for item in results}
    rows = []
    for case in cases:
        row = dict(case)
        row["result"] = result_by_id.get(case["case_id"])
        rows.append(row)
    successful = [row for row in rows if row["result"]]
    revised = [
        row
        for row in successful
        if row["result"]["adjudication"]["decision"] == "revise"
    ]
    low_confidence = [
        row
        for row in successful
        if row["result"]["adjudication"]["confidence"]
        < float(config.get("min_apply_confidence", 0.9))
    ]
    return {
        "schema": "fansub-final-adjudication-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {key: value for key, value in config.items() if "key" not in key},
        "summary": {
            "total": len(cases),
            "completed": len(successful),
            "missing_or_error": len(cases) - len(successful),
            "keep": len(successful) - len(revised),
            "revise": len(revised),
            "low_confidence": len(low_confidence),
        },
        "cases": rows,
    }


def apply_manual_overrides(
    report: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    """Merge stale-safe human decisions into a completed adjudication report.

    Overrides may also add a segment that was not selected by the automatic
    sampler. Every entry repeats the expected source and translation so a later
    pipeline run cannot silently receive a decision made against stale text.
    """
    if overrides.get("schema") != "fansub-final-manual-overrides-v1":
        raise ValueError("Unsupported manual override schema")

    merged = copy.deepcopy(report)
    rows = merged.setdefault("cases", [])
    by_key = {(int(row["episode"]), int(row["index"])): row for row in rows}
    episode_dirs = {int(row["episode"]): Path(row["episode_dir"]) for row in rows}
    reviewer = str(overrides.get("reviewer") or "human-review")
    seen: set[tuple[int, int]] = set()

    for override in overrides.get("overrides", []):
        episode = int(override["episode"])
        index = int(override["index"])
        key = (episode, index)
        if key in seen:
            raise ValueError(f"Duplicate manual override: E{episode:02d}:{index}")
        seen.add(key)

        expected_ja = str(override["ja"])
        expected_zh = str(override["current_zh"])
        row = by_key.get(key)
        if row is None:
            episode_dir = episode_dirs.get(episode)
            if episode_dir is None:
                raise ValueError(f"Episode is absent from report: E{episode:02d}")
            items = _read_json(episode_dir / "mqm_reviewed.json")
            if index < 0 or index >= len(items):
                raise ValueError(f"Segment index is out of range: E{episode:02d}:{index}")
            item = items[index]
            row = {
                "case_id": _case_id(episode, index, expected_ja, expected_zh),
                "episode": episode,
                "episode_dir": str(episode_dir),
                "index": index,
                "selection": "manual_override",
                "start": item.get("start"),
                "end": item.get("end"),
                "ja": str(item.get("ja", "")),
                "current_zh": str(item.get("text", "")),
                "context_before": [],
                "context_after": [],
                "fansub_reference": "",
                "fansub_alignment": None,
                "mqm_evidence": _compact_mqm_evidence(item.get("mqm_review")),
                "result": None,
            }
            rows.append(row)
            by_key[key] = row

        if str(row.get("ja", "")) != expected_ja:
            raise ValueError(f"Stale manual source at E{episode:02d}:{index}")
        if str(row.get("current_zh", "")) != expected_zh:
            raise ValueError(f"Stale manual translation at E{episode:02d}:{index}")

        decision = str(override["decision"])
        corrected_zh = override.get("corrected_zh")
        if decision not in VALID_DECISIONS:
            raise ValueError(f"Invalid manual decision at E{episode:02d}:{index}")
        if decision == "revise" and not str(corrected_zh or "").strip():
            raise ValueError(f"Manual revision has no correction: E{episode:02d}:{index}")
        if decision == "keep":
            corrected_zh = None

        previous = row.get("result") or {}
        row["result"] = {
            **previous,
            "case_id": row["case_id"],
            "status": "ok",
            "selection": row["selection"],
            "episode": episode,
            "index": index,
            "ja": expected_ja,
            "current_zh": expected_zh,
            "fansub_reference": row.get("fansub_reference", ""),
            "adjudication": {
                "decision": decision,
                "corrected_zh": corrected_zh,
                "severity": str(override.get("severity") or "manual"),
                "reason": str(override["reason"]),
                "confidence": 1.0,
                "reference_reliability": "manual_review",
                "model": f"manual:{reviewer}",
                "primary_model": f"manual:{reviewer}",
                "fallback_used": False,
                "attempt": 1,
                "time_s": 0.0,
            },
            "manual_review": {
                "reviewer": reviewer,
                "previous_adjudication": previous.get("adjudication"),
            },
        }

    successful = [row for row in rows if (row.get("result") or {}).get("status") == "ok"]
    revised = [
        row
        for row in successful
        if row["result"]["adjudication"]["decision"] == "revise"
    ]
    min_confidence = float(merged.get("config", {}).get("min_apply_confidence", 0.9))
    low_confidence = [
        row
        for row in successful
        if float(row["result"]["adjudication"]["confidence"]) < min_confidence
    ]
    merged["summary"] = {
        **merged.get("summary", {}),
        "total": len(rows),
        "completed": len(successful),
        "missing_or_error": len(rows) - len(successful),
        "keep": len(successful) - len(revised),
        "revise": len(revised),
        "low_confidence": len(low_confidence),
        "manual_overrides": len(seen),
    }
    return merged


def apply_report(report: dict[str, Any], *, min_confidence: float) -> dict[str, Any]:
    """Atomically apply confident final decisions to each episode JSON."""
    grouped: dict[Path, list[dict[str, Any]]] = {}
    for case in report.get("cases", []):
        result = case.get("result") or {}
        decision = result.get("adjudication") or {}
        if result.get("status") != "ok":
            continue
        grouped.setdefault(Path(case["episode_dir"]), []).append(case)

    applied = 0
    annotated = 0
    files = []
    summary_files = []
    for episode_dir, cases in grouped.items():
        path = episode_dir / "mqm_reviewed.json"
        items = _read_json(path)
        changed = False
        episode_applied = 0
        for case in cases:
            item = items[int(case["index"])]
            if str(item.get("ja", "")) != str(case["ja"]):
                raise ValueError(f"Stale source at {path}:{case['index']}")
            decision = case["result"]["adjudication"]
            should_revise = (
                decision["decision"] == "revise"
                and decision["confidence"] >= min_confidence
                and decision["corrected_zh"] != case["current_zh"]
            )
            valid_translations = {str(case["current_zh"])}
            if decision["decision"] == "revise" and decision.get("corrected_zh"):
                valid_translations.add(str(decision["corrected_zh"]))
            if str(item.get("text", "")) not in valid_translations:
                raise ValueError(f"Stale translation at {path}:{case['index']}")
            item["final_adjudication"] = {
                "decision": decision["decision"],
                "confidence": decision["confidence"],
                "reason": decision["reason"],
                "reference": case["fansub_reference"],
                "model": decision["model"],
            }
            annotated += 1
            if should_revise and decision["corrected_zh"] != item.get("text"):
                item["text"] = decision["corrected_zh"]
                applied += 1
                episode_applied += 1
            changed = True
        if changed:
            backup = path.with_suffix(f".before-final-adjudication{path.suffix}")
            if not backup.exists():
                shutil.copy2(path, backup)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(path)
            files.append(str(path))

        needs_review_cases = [
            case
            for case in cases
            if case.get("selection") == "needs_review"
            and case["result"]["adjudication"]["confidence"] >= min_confidence
        ]
        needs_review_revised = sum(
            case["result"]["adjudication"]["decision"] == "revise"
            for case in needs_review_cases
        )
        applicable_revisions = sum(
            case["result"]["adjudication"]["decision"] == "revise"
            and case["result"]["adjudication"]["confidence"] >= min_confidence
            and case["result"]["adjudication"]["corrected_zh"] != case["current_zh"]
            for case in cases
        )
        final_summary = {
            "schema": "fansub-final-adjudication-summary-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "reviewed": len(cases),
                "resolved_needs_review": len(needs_review_cases),
                "needs_review_kept": len(needs_review_cases) - needs_review_revised,
                "needs_review_revised": needs_review_revised,
                "applied_revisions": applicable_revisions,
                "changed_this_run": episode_applied,
            },
        }
        summary_path = episode_dir / "final_adjudication_summary.json"
        summary_temporary = summary_path.with_suffix(summary_path.suffix + ".tmp")
        summary_temporary.write_text(
            json.dumps(final_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary_temporary.replace(summary_path)
        summary_files.append(str(summary_path))
    return {
        "annotated": annotated,
        "applied": applied,
        "files": files,
        "summary_files": summary_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-root", type=Path)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--progress", type=Path)
    parser.add_argument(
        "--report-input",
        type=Path,
        help="Apply an existing completed report without rerunning model calls",
    )
    parser.add_argument("--approved-sample-per-episode", type=int, default=0)
    parser.add_argument("--manual-overrides", type=Path)
    parser.add_argument("--min-apply-confidence", type=float)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.report_input:
        report = _read_json(args.report_input)
        if args.manual_overrides:
            report = apply_manual_overrides(report, _read_json(args.manual_overrides))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(json.dumps(report["summary"], ensure_ascii=False))
        if args.apply:
            application = apply_report(
                report,
                min_confidence=(
                    args.min_apply_confidence
                    if args.min_apply_confidence is not None
                    else float(report.get("config", {}).get("min_apply_confidence", 0.9))
                ),
            )
            print(json.dumps(application, ensure_ascii=False))
        return 0 if report["summary"].get("missing_or_error", 0) == 0 else 1

    required = {
        "--prediction-root": args.prediction_root,
        "--reference-root": args.reference_root,
        "--config": args.config,
        "--output": args.output,
        "--progress": args.progress,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        parser.error(f"required unless --report-input is used: {', '.join(missing)}")

    config = _read_json(args.config)
    cases = collect_cases(
        args.prediction_root,
        args.reference_root,
        context_window=int(config.get("context_window", 5)),
        approved_sample_per_episode=args.approved_sample_per_episode,
    )
    results = run_adjudication(cases, config, args.progress)
    report = build_report(cases, results, config)
    if args.manual_overrides:
        report = apply_manual_overrides(report, _read_json(args.manual_overrides))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    if args.apply:
        application = apply_report(
            report,
            min_confidence=(
                args.min_apply_confidence
                if args.min_apply_confidence is not None
                else float(config.get("min_apply_confidence", 0.9))
            ),
        )
        print(json.dumps(application, ensure_ascii=False))
    return 0 if report["summary"]["missing_or_error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
