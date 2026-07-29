"""Read-only progress collector and dashboard for a full-season pipeline run."""

# The embedded, self-contained dashboard intentionally keeps CSS and JS compact.
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

SEASON_STAGES = (
    ("japanese_subtitle", "日文字幕", 2),
    ("translate", "Sakura 翻译", 10),
    ("multi_agent_review", "多 Agent 审查", 38),
    ("mqm_quality_review", "双裁判 MQM", 42),
    ("subtitle", "生成字幕", 1),
    ("embed_subtitle", "压制视频", 6),
    ("quality_check", "规则质检", 1),
)
STAGE_LABELS = dict((stage, label) for stage, label, _ in SEASON_STAGES)
STAGE_WEIGHTS = dict((stage, weight) for stage, _, weight in SEASON_STAGES)
REVIEW_FILES = {
    "multi_agent_review": ("multi_agent_review.progress.jsonl", "translated.json"),
    "mqm_quality_review": ("mqm_quality_review.progress.jsonl", "reviewed.json"),
}
EPISODE_PATTERN = re.compile(r"第\s*(\d{1,3})\s*集")
ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


def _iso_timestamp(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _redact_log(text: str) -> str:
    redacted = ANSI_PATTERN.sub("", text)
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[已隐藏]", redacted)
        else:
            redacted = pattern.sub("[已隐藏]", redacted)
    return redacted


class SeasonProgressMonitor:
    """Summarize durable pipeline artifacts without controlling the process."""

    def __init__(
        self,
        root: str | Path,
        episode_count: int = 14,
        stale_after_seconds: int = 300,
        log_line_count: int = 36,
    ) -> None:
        self.root = Path(root).resolve()
        self.episode_count = max(1, int(episode_count))
        self.stale_after_seconds = max(30, int(stale_after_seconds))
        self.log_line_count = max(5, int(log_line_count))
        self._jsonl_cache: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}
        self._count_cache: dict[Path, tuple[tuple[int, int], int]] = {}

    @staticmethod
    def _signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return stat.st_size, stat.st_mtime_ns
        except OSError:
            return None

    def _segment_count(self, path: Path) -> int:
        signature = self._signature(path)
        if signature is None:
            return 0
        cached = self._count_cache.get(path)
        if cached and cached[0] == signature:
            return cached[1]
        payload = _read_json(path)
        count = len(payload) if isinstance(payload, list) else 0
        self._count_cache[path] = (signature, count)
        return count

    def _review_progress(self, path: Path, total: int) -> dict[str, Any]:
        signature = self._signature(path)
        empty = {"processed": 0, "total": total, "percent": 0, "statuses": {}}
        if signature is None:
            return empty
        cached = self._jsonl_cache.get(path)
        if cached and cached[0] == signature:
            summary = dict(cached[1])
            summary["total"] = total
            summary["percent"] = round(100 * summary["processed"] / total, 1) if total else 0
            return summary

        records: dict[int, dict[str, Any]] = {}
        try:
            with path.open("r", encoding="utf-8", errors="replace") as source:
                for line in source:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    position = row.get("position") if isinstance(row, dict) else None
                    if isinstance(position, int) and position >= 0:
                        records[position] = row
        except OSError:
            return empty

        statuses = Counter(str(row.get("status") or "unknown") for row in records.values())
        processed = len(records)
        summary = {
            "processed": processed,
            "total": total,
            "percent": round(100 * processed / total, 1) if total else 0,
            "statuses": dict(sorted(statuses.items())),
        }
        self._jsonl_cache[path] = (signature, dict(summary))
        return summary

    def _episode_directories(self) -> dict[int, Path]:
        result: dict[int, Path] = {}
        if not self.root.is_dir():
            return result
        try:
            children = self.root.iterdir()
        except OSError:
            return result
        for path in children:
            if not path.is_dir():
                continue
            match = EPISODE_PATTERN.search(path.name)
            if match:
                result[int(match.group(1))] = path
        return result

    @staticmethod
    def _newest_mtime(path: Path | None) -> float | None:
        if path is None or not path.is_dir():
            return None
        newest: float | None = None
        try:
            for child in path.iterdir():
                if child.is_file():
                    modified = child.stat().st_mtime
                    newest = modified if newest is None else max(newest, modified)
        except OSError:
            return newest
        return newest

    def _quality_summary(self, episode_dir: Path | None) -> dict[str, Any]:
        if episode_dir is None:
            return {}
        result: dict[str, Any] = {}
        mqm = _read_json(episode_dir / "mqm_quality_report.json")
        if isinstance(mqm, dict) and isinstance(mqm.get("summary"), dict):
            result["mqm"] = {
                key: mqm["summary"].get(key, 0)
                for key in ("approved", "corrected", "needs_review", "errors", "applied")
            }
            final = _read_json(episode_dir / "final_adjudication_summary.json")
            if isinstance(final, dict) and isinstance(final.get("summary"), dict):
                final_summary = final["summary"]
                resolved = min(
                    int(result["mqm"]["needs_review"]),
                    int(final_summary.get("resolved_needs_review", 0)),
                )
                kept = min(resolved, int(final_summary.get("needs_review_kept", 0)))
                revised = min(
                    resolved - kept,
                    int(final_summary.get("needs_review_revised", 0)),
                )
                result["mqm"]["approved"] += kept
                result["mqm"]["corrected"] += revised
                result["mqm"]["needs_review"] -= resolved
                result["mqm"]["final_reviewed"] = int(
                    final_summary.get("reviewed", resolved)
                )
        quality = _read_json(episode_dir / "quality_report.json")
        if isinstance(quality, dict) and isinstance(quality.get("stats"), dict):
            result["rules"] = {
                key: quality["stats"].get(key, 0)
                for key in ("total_issues", "errors", "warnings", "info")
            }
        return result

    def _episode_snapshot(self, number: int, episode_dir: Path | None) -> dict[str, Any]:
        checkpoint = _read_json(episode_dir / "checkpoint.json") if episode_dir else None
        checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
        completed = {
            stage for stage, _, _ in SEASON_STAGES
            if isinstance(checkpoint.get(stage), dict)
            and checkpoint[stage].get("status") == "completed"
        }
        failed = {
            stage for stage, _, _ in SEASON_STAGES
            if isinstance(checkpoint.get(stage), dict)
            and checkpoint[stage].get("status") == "failed"
        }
        active = next((stage for stage, _, _ in SEASON_STAGES if stage not in completed), None)
        review = {"processed": 0, "total": 0, "percent": 0, "statuses": {}}
        if active in REVIEW_FILES and episode_dir:
            progress_name, source_name = REVIEW_FILES[active]
            total = self._segment_count(episode_dir / source_name)
            review = self._review_progress(episode_dir / progress_name, total)

        stages = []
        weighted_progress = 0.0
        for stage, label, weight in SEASON_STAGES:
            if stage in completed:
                state, fraction = "completed", 1.0
            elif stage in failed:
                state, fraction = "failed", 0.0
            elif stage == active:
                state = "active"
                fraction = review["percent"] / 100 if stage in REVIEW_FILES else 0.0
            else:
                state, fraction = "pending", 0.0
            weighted_progress += weight * fraction
            stages.append({"id": stage, "label": label, "state": state})

        if len(completed) == len(SEASON_STAGES):
            state = "completed"
        elif failed:
            state = "failed"
        elif checkpoint or review["processed"]:
            state = "running"
        else:
            state = "pending"
        updated = self._newest_mtime(episode_dir)
        return {
            "number": number,
            "name": episode_dir.name if episode_dir else f"第{number:02d}集",
            "state": state,
            "percent": round(weighted_progress, 1),
            "active_stage": active,
            "active_stage_label": STAGE_LABELS.get(active, "已完成"),
            "completed_stages": len(completed),
            "total_stages": len(SEASON_STAGES),
            "stages": stages,
            "review": review,
            "quality": self._quality_summary(episode_dir),
            "updated_at": _iso_timestamp(updated),
            "_updated_epoch": updated,
        }

    def _log_tail(self) -> tuple[str, float | None]:
        paths = [self.root / "full_run_v3.stdout.log", self.root / "full_run.stdout.log"]
        path = next((candidate for candidate in paths if candidate.is_file()), None)
        if path is None:
            return "", None
        try:
            size = path.stat().st_size
            with path.open("rb") as source:
                source.seek(max(0, size - 65_536))
                lines = source.read().decode("utf-8", errors="replace").splitlines()
            return _redact_log("\n".join(lines[-self.log_line_count :])), path.stat().st_mtime
        except OSError:
            return "", None

    def snapshot(self) -> dict[str, Any]:
        directories = self._episode_directories()
        episodes = [
            self._episode_snapshot(number, directories.get(number))
            for number in range(1, self.episode_count + 1)
        ]
        log_tail, log_mtime = self._log_tail()
        activity_times = [
            timestamp for timestamp in [log_mtime, *(item["_updated_epoch"] for item in episodes)]
            if timestamp is not None
        ]
        last_activity = max(activity_times) if activity_times else None
        now = time.time()
        completed_episodes = sum(item["state"] == "completed" for item in episodes)
        failed = any(item["state"] == "failed" for item in episodes)
        if completed_episodes == self.episode_count:
            status = "completed"
        elif failed:
            status = "failed"
        elif last_activity is not None and now - last_activity <= self.stale_after_seconds:
            status = "running"
        elif last_activity is not None:
            status = "stale"
        else:
            status = "waiting"

        active_episode = next((item for item in episodes if item["state"] == "running"), None)
        if active_episode is None:
            active_episode = next((item for item in episodes if item["state"] != "completed"), None)
        overall = sum(item["percent"] for item in episodes) / self.episode_count
        for episode in episodes:
            episode.pop("_updated_epoch", None)
        return {
            "status": status,
            "status_label": {
                "running": "运行正常",
                "completed": "全季完成",
                "failed": "发现失败阶段",
                "stale": "等待新进度",
                "waiting": "尚未开始",
            }[status],
            "overall_percent": round(overall, 1),
            "completed_episodes": completed_episodes,
            "episode_count": self.episode_count,
            "active_episode": active_episode["number"] if active_episode else None,
            "last_activity_at": _iso_timestamp(last_activity),
            "captured_at": _iso_timestamp(now),
            "root_name": self.root.name,
            "episodes": episodes,
            "log_tail": log_tail,
        }


MONITOR_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>轻音少女全季进度 · Anime Accurate Sub</title>
<style>
:root{color-scheme:dark;--ink:#f7f5f2;--muted:#a9b0bd;--bg:#090c12;--panel:#111620;--line:#263040;--pink:#ff6fae;--mint:#55d6be;--amber:#ffca72;--red:#ff7272}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at 18% -10%,#34213a 0,transparent 34%),radial-gradient(circle at 92% 4%,#153b3a 0,transparent 28%),var(--bg);font:15px/1.5 Inter,"Microsoft YaHei UI",system-ui,sans-serif}main{width:min(1220px,94vw);margin:0 auto;padding:42px 0 70px}.top{display:flex;justify-content:space-between;gap:24px;align-items:flex-start}.eyebrow{color:var(--pink);font-size:12px;letter-spacing:.18em;text-transform:uppercase;font-weight:800}h1{font-size:clamp(30px,5vw,56px);line-height:1.08;margin:8px 0 10px;letter-spacing:-.035em}.sub{margin:0;color:var(--muted);max-width:670px}.live{display:flex;align-items:center;gap:9px;padding:10px 14px;border:1px solid var(--line);border-radius:99px;background:#111620cc;white-space:nowrap}.live i{width:9px;height:9px;border-radius:50%;background:var(--muted)}.live.running i{background:var(--mint);box-shadow:0 0 0 6px #55d6be20;animation:pulse 1.8s infinite}.live.failed i{background:var(--red)}.live.stale i{background:var(--amber)}@keyframes pulse{50%{box-shadow:0 0 0 11px #55d6be00}}.summary{display:grid;grid-template-columns:230px 1fr;gap:18px;margin:30px 0}.panel{background:linear-gradient(150deg,#151b27e8,#0e131ce8);border:1px solid var(--line);border-radius:20px;box-shadow:0 24px 65px #0005}.ring-card{display:grid;place-items:center;padding:25px}.ring{--p:0;width:154px;aspect-ratio:1;border-radius:50%;display:grid;place-items:center;background:radial-gradient(circle closest-side,#111620 76%,transparent 77%),conic-gradient(var(--pink) calc(var(--p)*1%),#273040 0)}.ring strong{font-size:31px}.ring span{display:block;color:var(--muted);font-size:11px;text-align:center}.now{padding:24px 26px}.now-head{display:flex;justify-content:space-between;gap:16px}.now h2{margin:3px 0 4px;font-size:23px}.meta{color:var(--muted);font-size:13px}.review-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:20px}.stat{background:#0a0e15;border:1px solid #202938;border-radius:12px;padding:12px}.stat b{font-size:21px;display:block}.stat span{color:var(--muted);font-size:12px}.section-title{display:flex;align-items:end;justify-content:space-between;margin:35px 0 13px}.section-title h2{margin:0}.episodes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.episode{padding:17px 18px;transition:border-color .2s,transform .2s}.episode.active{border-color:#ff6fae88;transform:translateY(-1px)}.ep-head{display:flex;align-items:center;justify-content:space-between;gap:15px}.ep-name{font-weight:750}.ep-pct{font-variant-numeric:tabular-nums;color:var(--muted)}.bar{height:7px;border-radius:9px;background:#242d3b;overflow:hidden;margin:11px 0}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--pink),#a589ff,var(--mint));border-radius:inherit}.stages{display:grid;grid-template-columns:repeat(7,1fr);gap:5px}.stage{height:6px;border-radius:9px;background:#2b3442}.stage.completed{background:var(--mint)}.stage.active{background:var(--pink);box-shadow:0 0 9px #ff6fae88}.stage.failed{background:var(--red)}.ep-detail{display:flex;justify-content:space-between;gap:10px;margin-top:9px;color:var(--muted);font-size:12px}.terminal{margin-top:13px;padding:18px}.terminal pre{margin:12px 0 0;padding:16px;max-height:350px;overflow:auto;border-radius:12px;background:#070a0f;color:#bdc9d8;font:12px/1.65 ui-monospace,Consolas,monospace;white-space:pre-wrap}.empty{color:var(--muted)}.error{padding:24px;color:#ffd0d0}.foot{margin-top:13px;color:var(--muted);font-size:12px;text-align:right}@media(max-width:780px){main{padding-top:25px}.top{display:block}.live{margin-top:18px;width:max-content}.summary{grid-template-columns:1fr}.ring-card{padding:20px}.ring{width:130px}.episodes{grid-template-columns:1fr}.review-grid{grid-template-columns:1fr 1fr}.now-head{display:block}}
</style></head><body><main>
<header class="top"><div><div class="eyebrow">Anime Accurate Sub · Quality Run</div><h1>轻音少女 S1<br>全流程监控</h1><p class="sub">Sakura 翻译、SenseNova 多 Agent 审查与双裁判 MQM 的实时执行状态。页面每 4 秒自动读取持久化进度。</p></div><div id="live" class="live"><i></i><span>正在连接</span></div></header>
<section id="content" aria-live="polite"><div class="panel error">正在读取全季进度……</div></section>
<div id="foot" class="foot"></div>
</main><script>
const content=document.querySelector('#content'),live=document.querySelector('#live'),foot=document.querySelector('#foot');
const esc=s=>String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
const n=v=>Number.isFinite(Number(v))?Number(v):0;
function timeLabel(value){if(!value)return '暂无';try{return new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(value))}catch{return value}}
function render(data){live.className='live '+esc(data.status);live.innerHTML=`<i></i><span>${esc(data.status_label)}</span>`;const current=data.episodes.find(x=>x.number===data.active_episode);const r=current?.review||{},s=r.statuses||{};const currentBody=current?`<div class="now-head"><div><div class="eyebrow">当前任务 · 第 ${String(current.number).padStart(2,'0')} 集</div><h2>${esc(current.active_stage_label)}</h2><div class="meta">${r.total?`已审查 ${n(r.processed)} / ${n(r.total)} 句 · ${n(r.percent).toFixed(1)}%`:`已完成 ${n(current.completed_stages)} / ${n(current.total_stages)} 个阶段`}</div></div><div class="meta">最近写入 ${timeLabel(current.updated_at)}</div></div><div class="review-grid"><div class="stat"><b>${n(s.approved)}</b><span>审查通过</span></div><div class="stat"><b>${n(s.corrected)}</b><span>自动修正</span></div><div class="stat"><b>${n(s.needs_review)}</b><span>待人工复核</span></div><div class="stat"><b>${n(s.error)+n(s.errors)}</b><span>调用/解析异常</span></div></div>`:'<div class="empty">全部集数已处理完成。</div>';
const cards=data.episodes.map(ep=>{const review=ep.review||{},detail=review.total?`${n(review.processed)} / ${n(review.total)} 句`:`${n(ep.completed_stages)} / ${n(ep.total_stages)} 阶段`;return `<article class="panel episode ${ep.number===data.active_episode?'active':''}"><div class="ep-head"><span class="ep-name">第 ${String(ep.number).padStart(2,'0')} 集</span><span class="ep-pct">${n(ep.percent).toFixed(1)}%</span></div><div class="bar"><i style="width:${Math.max(0,Math.min(100,n(ep.percent)))}%"></i></div><div class="stages" aria-label="七阶段进度">${ep.stages.map(stage=>`<i class="stage ${esc(stage.state)}" title="${esc(stage.label)}：${esc(stage.state)}"></i>`).join('')}</div><div class="ep-detail"><span>${esc(ep.state==='completed'?'全部完成':ep.active_stage_label)}</span><span>${detail}</span></div></article>`}).join('');
content.innerHTML=`<section class="summary"><div class="panel ring-card"><div class="ring" style="--p:${n(data.overall_percent)}"><div><strong>${n(data.overall_percent).toFixed(1)}%</strong><span>全季质量流程</span></div></div></div><div class="panel now">${currentBody}</div></section><div class="section-title"><h2>${n(data.episode_count)} 集执行矩阵</h2><span class="meta">已完整交付 ${n(data.completed_episodes)} / ${n(data.episode_count)} 集</span></div><section class="episodes">${cards}</section><div class="section-title"><h2>实时日志</h2><span class="meta">最后心跳 ${timeLabel(data.last_activity_at)}</span></div><section class="panel terminal"><pre>${esc(data.log_tail)||'暂时没有日志输出'}</pre></section>`;foot.textContent=`数据刷新于 ${timeLabel(data.captured_at)} · 只读监控，不会控制流水线`}
async function refresh(){try{const response=await fetch('/api/monitor',{cache:'no-store'});if(!response.ok)throw new Error(response.statusText);render(await response.json())}catch(error){live.className='live failed';live.innerHTML='<i></i><span>读取失败</span>';content.innerHTML=`<div class="panel error">暂时无法读取进度：${esc(error.message)}。页面会自动重试。</div>`}}
refresh();setInterval(refresh,4000);
</script></body></html>"""
