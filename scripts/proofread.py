"""Export, import, audit, and interactively correct translated subtitle segments."""

import argparse
import hashlib
import json
import shutil
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from scripts.subtitle_gen import generate as generate_subtitles


SHEET_SCHEMA = "anime-accurate-sub/proofread-v1"


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _segments_from_document(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, list):
        segments = document
    elif isinstance(document, dict) and isinstance(document.get("segments"), list):
        segments = document["segments"]
    else:
        raise ValueError("译文 JSON 必须是片段数组，或包含 segments 数组")
    if not all(isinstance(item, dict) for item in segments):
        raise ValueError("译文 JSON 中存在非对象片段")
    return segments


def source_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quality_reasons(quality_report: str | Path | None) -> dict[int, list[dict[str, str]]]:
    reasons: dict[int, list[dict[str, str]]] = {}
    if not quality_report or not Path(quality_report).exists():
        return reasons
    report = _load_json(quality_report)
    for issue in report.get("review_queue", report.get("issues", [])):
        try:
            index = int(issue["segment_index"])
        except (KeyError, TypeError, ValueError):
            continue
        reason = {
            "rule": str(issue.get("rule", "quality_review")),
            "severity": str(issue.get("severity", "warning")),
            "message": str(issue.get("message", "建议人工复核")),
        }
        if reason not in reasons.setdefault(index, []):
            reasons[index].append(reason)
    return reasons


def build_proofread_sheet(
    translated_path: str | Path,
    quality_report: str | Path | None = None,
    only_review: bool = False,
) -> dict[str, Any]:
    """Build a portable correction sheet from translated segments and quality issues."""
    translated_path = Path(translated_path).resolve()
    segments = _segments_from_document(_load_json(translated_path))
    reasons = quality_reasons(quality_report)
    items = []
    for index, segment in enumerate(segments):
        segment_reasons = [
            reason
            for reason in reasons.get(index, [])
            if not (
                segment.get("proofread_status") == "corrected"
                and reason["rule"] == "translation_fallback"
            )
        ]
        if only_review and not segment_reasons:
            continue
        text = str(segment.get("text", ""))
        items.append(
            {
                "index": index,
                "start": segment.get("start"),
                "end": segment.get("end"),
                "ja": segment.get("ja", segment.get("source_text", "")),
                "translated_text": text,
                "corrected_text": text,
                "status": "needs_review" if segment_reasons else "unreviewed",
                "reasons": segment_reasons,
                "note": "",
            }
        )
    return {
        "schema": SHEET_SCHEMA,
        "generated_at": timestamp(),
        "source_file": str(translated_path),
        "source_sha256": source_digest(translated_path),
        "only_review": only_review,
        "items": items,
    }


def export_sheet(
    translated_path: str | Path,
    output_path: str | Path,
    quality_report: str | Path | None = None,
    only_review: bool = False,
) -> dict[str, Any]:
    sheet = build_proofread_sheet(translated_path, quality_report, only_review)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(sheet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return sheet


def _atomic_write_json(path: Path, document: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _append_history(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [existing.rstrip("\n")] if existing else []
    lines.extend(json.dumps(entry, ensure_ascii=False) for entry in entries)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)


def _corrections_from_sheet(sheet_or_path: dict[str, Any] | str | Path) -> dict[str, Any]:
    sheet = _load_json(sheet_or_path) if isinstance(sheet_or_path, (str, Path)) else sheet_or_path
    if not isinstance(sheet, dict) or not isinstance(sheet.get("items"), list):
        raise ValueError("校对稿必须包含 items 数组")
    if sheet.get("schema") not in {None, SHEET_SCHEMA}:
        raise ValueError(f"不支持的校对稿格式：{sheet.get('schema')}")
    return sheet


def apply_corrections(
    translated_path: str | Path,
    sheet_or_path: dict[str, Any] | str | Path,
    history_path: str | Path | None = None,
    operator: str = "manual",
    force: bool = False,
    create_backup: bool = True,
) -> dict[str, Any]:
    """Validate all edits first, then atomically update translated JSON and audit history."""
    translated_path = Path(translated_path).resolve()
    sheet = _corrections_from_sheet(sheet_or_path)
    expected_digest = sheet.get("source_sha256")
    current_digest = source_digest(translated_path)
    if expected_digest and expected_digest != current_digest and not force:
        raise ValueError("译文文件已变化，校对稿 SHA-256 不匹配；请重新导出或使用 --force")

    document = _load_json(translated_path)
    segments = _segments_from_document(document)
    planned = []
    seen_indexes = set()
    for raw in sheet["items"]:
        if not isinstance(raw, dict) or "corrected_text" not in raw:
            continue
        try:
            index = int(raw["index"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("校对项缺少有效 index") from error
        if index in seen_indexes:
            raise ValueError(f"校对稿包含重复 index：{index}")
        seen_indexes.add(index)
        if not 0 <= index < len(segments):
            raise ValueError(f"校对 index 越界：{index}")
        corrected = str(raw["corrected_text"]).strip()
        if not corrected:
            raise ValueError(f"校对文本不能为空：index {index}")
        previous = str(segments[index].get("text", ""))
        expected = raw.get("translated_text", raw.get("expected_text"))
        if expected is not None and str(expected) != previous and not force:
            raise ValueError(f"index {index} 原译文已变化，请重新导出校对稿")
        if raw.get("start") is not None:
            actual_start = float(segments[index].get("start", -1))
            if abs(float(raw["start"]) - actual_start) > 0.01 and not force:
                raise ValueError(f"index {index} 时间轴已变化，请重新导出校对稿")
        if corrected != previous:
            planned.append((index, previous, corrected, str(raw.get("note", "")).strip()))

    if not planned:
        return {
            "source_file": str(translated_path),
            "applied": 0,
            "indexes": [],
            "backup_file": None,
            "history_file": str(history_path or translated_path.with_name("proofread_history.jsonl")),
        }

    updated_document = deepcopy(document)
    updated_segments = _segments_from_document(updated_document)
    applied_at = timestamp()
    audit_entries = []
    for index, previous, corrected, note in planned:
        entry = {
            "timestamp": applied_at,
            "source_file": str(translated_path),
            "index": index,
            "start": updated_segments[index].get("start"),
            "end": updated_segments[index].get("end"),
            "ja": updated_segments[index].get("ja", updated_segments[index].get("source_text")),
            "previous_text": previous,
            "corrected_text": corrected,
            "note": note,
            "operator": operator,
        }
        history = list(updated_segments[index].get("proofread_history", []))
        history.append(
            {
                "timestamp": applied_at,
                "previous_text": previous,
                "corrected_text": corrected,
                "note": note,
                "operator": operator,
            }
        )
        updated_segments[index]["text"] = corrected
        updated_segments[index]["proofread_status"] = "corrected"
        updated_segments[index]["proofread_history"] = history
        audit_entries.append(entry)

    backup_path = None
    if create_backup:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        backup_path = translated_path.with_name(
            f"{translated_path.stem}.before-proofread.{stamp}{translated_path.suffix}"
        )
        shutil.copy2(translated_path, backup_path)
    _atomic_write_json(translated_path, updated_document)
    resolved_history = Path(history_path) if history_path else translated_path.with_name(
        "proofread_history.jsonl"
    )
    _append_history(resolved_history, audit_entries)
    return {
        "source_file": str(translated_path),
        "applied": len(planned),
        "indexes": [item[0] for item in planned],
        "backup_file": str(backup_path) if backup_path else None,
        "history_file": str(resolved_history),
    }


def regenerate_subtitles(
    translated_path: str | Path,
    output_base: str | Path | None = None,
    speaker_map: str | Path | None = None,
) -> dict[str, str]:
    """Regenerate canonical SRT and ASS files after applying corrections."""
    translated_path = Path(translated_path).resolve()
    base = Path(output_base) if output_base else translated_path.parent / translated_path.parent.name
    srt_path = base.with_suffix(".srt")
    ass_path = base.with_suffix(".ass")
    generate_subtitles(str(translated_path), str(srt_path), speaker_map=speaker_map)
    generate_subtitles(
        str(translated_path), str(ass_path), style="anime", speaker_map=speaker_map
    )
    return {"srt": str(srt_path), "ass": str(ass_path)}


def interactive_review(
    translated_path: str | Path,
    quality_report: str | Path | None = None,
    only_review: bool = True,
    operator: str = "interactive-cli",
) -> dict[str, Any]:
    """Review segments in a terminal; blank keeps text, q saves edits and exits."""
    sheet = build_proofread_sheet(translated_path, quality_report, only_review)
    corrections = []
    for item in sheet["items"]:
        reasons = ", ".join(reason["rule"] for reason in item["reasons"]) or "manual"
        print(f"\n[{item['index']}] {item['start']} -> {item['end']} ({reasons})")
        print(f"日文: {item['ja']}")
        print(f"当前: {item['translated_text']}")
        corrected = input("修正（回车保留，:q 保存退出）: ").strip()
        if corrected == ":q":
            break
        if corrected and corrected != item["translated_text"]:
            item["corrected_text"] = corrected
            item["note"] = "interactive review"
            corrections.append(item)
    sheet["items"] = corrections
    return apply_corrections(translated_path, sheet, operator=operator)


def main() -> None:
    parser = argparse.ArgumentParser(description="Subtitle proofreading workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export a portable JSON review sheet")
    export_parser.add_argument("--input", required=True)
    export_parser.add_argument("--output", required=True)
    export_parser.add_argument("--quality-report", default="")
    export_parser.add_argument("--only-review", action="store_true")

    apply_parser = subparsers.add_parser("apply", help="Apply an edited JSON review sheet")
    apply_parser.add_argument("--input", required=True)
    apply_parser.add_argument("--sheet", required=True)
    apply_parser.add_argument("--history", default="")
    apply_parser.add_argument("--operator", default="manual-import")
    apply_parser.add_argument("--force", action="store_true")
    apply_parser.add_argument("--regenerate", action="store_true")
    apply_parser.add_argument("--subtitle-base", default="")
    apply_parser.add_argument("--speaker-map", default="")

    interactive_parser = subparsers.add_parser("interactive", help="Correct lines in a terminal")
    interactive_parser.add_argument("--input", required=True)
    interactive_parser.add_argument("--quality-report", default="")
    interactive_parser.add_argument("--all", action="store_true")
    interactive_parser.add_argument("--operator", default="interactive-cli")

    args = parser.parse_args()
    if args.command == "export":
        sheet = export_sheet(
            args.input,
            args.output,
            args.quality_report or None,
            args.only_review,
        )
        print(f"Exported {len(sheet['items'])} lines to {args.output}")
        return
    if args.command == "apply":
        result = apply_corrections(
            args.input,
            args.sheet,
            history_path=args.history or None,
            operator=args.operator,
            force=args.force,
        )
        if args.regenerate:
            result["subtitles"] = regenerate_subtitles(
                args.input,
                args.subtitle_base or None,
                args.speaker_map or None,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    result = interactive_review(
        args.input,
        args.quality_report or None,
        only_review=not args.all,
        operator=args.operator,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
