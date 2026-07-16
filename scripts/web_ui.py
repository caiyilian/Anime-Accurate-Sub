"""Local FastAPI UI for starting and monitoring subtitle pipeline jobs."""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.checkpoint import PIPELINE_STAGES


DEFAULT_JOB_ROOT = PROJECT_ROOT / ".omo" / "web_jobs"
ALLOWED_BACKENDS = {"sakura", "galtransl", "qwen", "external"}
ALLOWED_VIDEO_EXTENSIONS = {
    ".avi",
    ".flv",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
}
DOWNLOADABLE_NAMES = {"translated.json", "quality_report.json"}
DOWNLOADABLE_SUFFIXES = {".ass", ".srt"}
DOWNLOADABLE_VIDEO_SUFFIXES = ("_subs.mp4", "_preview.mp4", "_proofread_subs.mp4")


def utc_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_upload_name(filename: str) -> str:
    """Return a filesystem-safe basename while preserving Unicode episode names."""
    name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).rstrip(". ")
    if not name or name in {".", ".."}:
        raise ValueError("视频文件名无效")
    if Path(name).suffix.lower() not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError(f"不支持的视频格式：{Path(name).suffix or '无扩展名'}")
    return name


def validate_job_options(options: dict[str, Any]) -> dict[str, Any]:
    backend = str(options.get("backend", "sakura")).lower().strip()
    if backend not in ALLOWED_BACKENDS:
        raise ValueError(f"不支持的翻译后端：{backend}")
    batch_size = int(options.get("translation_batch_size") or 0)
    if batch_size < 0 or batch_size > 100:
        raise ValueError("翻译批大小必须在 0 到 100 之间")
    return {
        "backend": backend,
        "quality_check": bool(options.get("quality_check", False)),
        "translation_batch_size": batch_size,
    }


def build_pipeline_command(
    input_path: str | Path,
    output_dir: str | Path,
    options: dict[str, Any],
    python_executable: str | None = None,
) -> list[str]:
    """Build a shell-free pipeline command from validated UI options."""
    normalized = validate_job_options(options)
    command = [
        python_executable or sys.executable,
        str(PROJECT_ROOT / "scripts" / "anime_sub.py"),
        str(Path(input_path)),
        "--output-dir",
        str(Path(output_dir)),
        "--backend",
        normalized["backend"],
    ]
    if normalized["quality_check"]:
        command.append("--quality-check")
    if normalized["translation_batch_size"]:
        command.extend(
            ["--translation-batch-size", str(normalized["translation_batch_size"])]
        )
    return command


def checkpoint_progress(output_dir: str | Path, quality_check: bool = False) -> dict[str, Any]:
    """Summarize the newest pipeline checkpoint below a Web job output directory."""
    stages = PIPELINE_STAGES if quality_check else PIPELINE_STAGES[:-1]
    checkpoints = sorted(
        Path(output_dir).rglob("checkpoint.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    state: dict[str, Any] = {}
    checkpoint_path = ""
    if checkpoints:
        checkpoint_path = str(checkpoints[0])
        try:
            state = json.loads(checkpoints[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    completed = [
        stage for stage in stages if state.get(stage, {}).get("status") == "completed"
    ]
    failed = [stage for stage in stages if state.get(stage, {}).get("status") == "failed"]
    active = next((stage for stage in stages if stage not in completed), "completed")
    return {
        "completed": len(completed),
        "total": len(stages),
        "percent": round(100 * len(completed) / len(stages)) if stages else 100,
        "active_stage": failed[0] if failed else active,
        "failed_stages": failed,
        "checkpoint": checkpoint_path,
    }


def is_downloadable_result(path: Path) -> bool:
    return (
        path.name in DOWNLOADABLE_NAMES
        or path.suffix.lower() in DOWNLOADABLE_SUFFIXES
        or path.name.lower().endswith(DOWNLOADABLE_VIDEO_SUFFIXES)
    )


class JobManager:
    """Persistent, process-backed Web job registry."""

    def __init__(self, root: str | Path = DEFAULT_JOB_ROOT):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen] = {}
        self._mark_orphaned_jobs()

    def _job_dir(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", job_id):
            raise KeyError(job_id)
        return self.root / job_id

    def _metadata_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    def _load(self, job_id: str) -> dict[str, Any]:
        path = self._metadata_path(job_id)
        if not path.exists():
            raise KeyError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, record: dict[str, Any]) -> None:
        path = self._metadata_path(record["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    def _mark_orphaned_jobs(self) -> None:
        for path in self.root.glob("*/job.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("status") == "running":
                    record["status"] = "interrupted"
                    record["finished_at"] = utc_timestamp()
                    self._save(record)
            except (KeyError, OSError, json.JSONDecodeError):
                continue

    def create_job(self, filename: str, options: dict[str, Any]) -> tuple[dict[str, Any], Path]:
        upload_name = safe_upload_name(filename)
        normalized = validate_job_options(options)
        job_id = uuid.uuid4().hex[:12]
        job_dir = self._job_dir(job_id)
        input_dir = job_dir / "input"
        output_dir = job_dir / "output"
        input_dir.mkdir(parents=True)
        output_dir.mkdir()
        input_path = input_dir / upload_name
        record = {
            "id": job_id,
            "filename": upload_name,
            "status": "uploading",
            "created_at": utc_timestamp(),
            "started_at": None,
            "finished_at": None,
            "pid": None,
            "exit_code": None,
            "options": normalized,
            "input_path": str(input_path),
            "output_dir": str(output_dir),
        }
        with self._lock:
            self._save(record)
        return record, input_path

    def save_upload(self, input_path: Path, source: BinaryIO) -> int:
        total = 0
        with input_path.open("wb") as destination:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                destination.write(chunk)
                total += len(chunk)
        if total == 0:
            input_path.unlink(missing_ok=True)
            raise ValueError("上传的视频为空")
        return total

    def start_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._load(job_id)
            if record["status"] not in {"uploading", "pending"}:
                raise ValueError(f"任务当前状态不能启动：{record['status']}")
            input_path = Path(record["input_path"])
            if not input_path.is_file():
                raise FileNotFoundError(input_path)
            command = build_pipeline_command(
                input_path, record["output_dir"], record["options"]
            )
            log_path = self._job_dir(job_id) / "pipeline.log"
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            with log_path.open("ab") as log_file:
                process = subprocess.Popen(
                    command,
                    cwd=str(PROJECT_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
            self._processes[job_id] = process
            record.update(
                {
                    "status": "running",
                    "started_at": utc_timestamp(),
                    "pid": process.pid,
                    "command": command,
                    "upload_bytes": input_path.stat().st_size,
                }
            )
            self._save(record)
            return self._public_record(record)

    def fail_job(self, job_id: str, error: Exception) -> None:
        with self._lock:
            record = self._load(job_id)
            record.update(
                {
                    "status": "failed",
                    "finished_at": utc_timestamp(),
                    "error": str(error)[:500],
                }
            )
            self._save(record)

    def _refresh(self, record: dict[str, Any]) -> dict[str, Any]:
        process = self._processes.get(record["id"])
        if record.get("status") == "running" and process is not None:
            exit_code = process.poll()
            if exit_code is not None:
                record["exit_code"] = exit_code
                record["status"] = "completed" if exit_code == 0 else "failed"
                record["finished_at"] = utc_timestamp()
                self._processes.pop(record["id"], None)
                self._save(record)
        return record

    def _outputs(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        output_dir = Path(record["output_dir"])
        results = []
        if not output_dir.exists():
            return results
        for path in sorted(output_dir.rglob("*")):
            if not path.is_file():
                continue
            if not is_downloadable_result(path):
                continue
            relative = path.relative_to(output_dir).as_posix()
            results.append(
                {
                    "name": path.name,
                    "path": relative,
                    "size": path.stat().st_size,
                    "download_url": f"/api/jobs/{record['id']}/files/{quote(relative)}",
                }
            )
        return results

    def _log_tail(self, job_id: str, max_bytes: int = 16_384) -> str:
        path = self._job_dir(job_id) / "pipeline.log"
        if not path.exists():
            return ""
        with path.open("rb") as file:
            file.seek(max(0, path.stat().st_size - max_bytes))
            return file.read().decode("utf-8", errors="replace")[-8000:]

    def _public_record(self, record: dict[str, Any]) -> dict[str, Any]:
        public = {
            key: value
            for key, value in record.items()
            if key not in {"input_path", "output_dir", "command"}
        }
        public["progress"] = checkpoint_progress(
            record["output_dir"], record["options"]["quality_check"]
        )
        public["outputs"] = self._outputs(record)
        public["log_tail"] = self._log_tail(record["id"])
        return public

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return self._public_record(self._refresh(self._load(job_id)))

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs = []
        for path in self.root.glob("*/job.json"):
            try:
                jobs.append(self.get_job(path.parent.name))
            except (KeyError, OSError, json.JSONDecodeError):
                continue
        return sorted(jobs, key=lambda item: item["created_at"], reverse=True)

    def downloadable_path(self, job_id: str, relative_path: str) -> Path:
        record = self._load(job_id)
        output_dir = Path(record["output_dir"]).resolve()
        candidate = (output_dir / relative_path).resolve()
        if not candidate.is_relative_to(output_dir) or not candidate.is_file():
            raise FileNotFoundError(relative_path)
        if not is_downloadable_result(candidate):
            raise FileNotFoundError(relative_path)
        return candidate


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Anime Accurate Sub</title>
  <style>
    :root { color-scheme: dark; --bg:#0c111b; --card:#151d2b; --line:#2b3850; --accent:#ff78b5; --text:#e8edf6; --muted:#9ba9bd; }
    * { box-sizing:border-box } body { margin:0; font:15px/1.5 system-ui,sans-serif; background:radial-gradient(circle at top,#1d2940,var(--bg) 45%); color:var(--text) }
    main { width:min(1040px,92vw); margin:40px auto 80px } h1 { margin-bottom:4px; font-size:clamp(28px,5vw,46px) } .lead { color:var(--muted); margin-top:0 }
    .panel,.job { background:color-mix(in srgb,var(--card) 92%,transparent); border:1px solid var(--line); border-radius:16px; padding:20px; box-shadow:0 18px 45px #0005 }
    form { display:grid; grid-template-columns:2fr 1fr 1fr; gap:14px; align-items:end } label { display:grid; gap:6px; color:var(--muted) }
    input,select,button { width:100%; padding:11px 12px; border-radius:9px; border:1px solid var(--line); background:#0d1420; color:var(--text) }
    button { cursor:pointer; border:0; background:linear-gradient(120deg,var(--accent),#9c7cff); color:#111522; font-weight:750 } button:disabled { opacity:.55 }
    .checks { display:flex; gap:16px; align-items:center; min-height:43px }.checks label { display:flex; flex-direction:row; align-items:center }.checks input { width:auto }
    h2 { margin-top:34px }.jobs { display:grid; gap:14px }.job header { display:flex; justify-content:space-between; gap:12px }.pill { color:var(--accent); font-weight:700 }
    progress { width:100%; height:10px; accent-color:var(--accent) }.meta,.outputs { color:var(--muted); font-size:13px }.outputs a { color:#9ed7ff; margin-right:14px }
    pre { max-height:220px; overflow:auto; padding:12px; background:#090e16; border-radius:9px; color:#b9c7d9; white-space:pre-wrap }
    #message { min-height:24px; color:#ffd09e } @media(max-width:720px){ form{grid-template-columns:1fr}.checks{min-height:auto} }
  </style>
</head>
<body><main>
  <h1>Anime Accurate Sub</h1><p class="lead">上传视频，后台运行完整字幕流水线，并从 checkpoint 查看真实进度。</p>
  <section class="panel">
    <form id="job-form">
      <label>视频文件<input name="video" type="file" accept="video/*,.mkv,.ts" required></label>
      <label>翻译后端<select name="backend"><option value="sakura">Sakura</option><option value="galtransl">GalTransl</option><option value="qwen">Qwen</option><option value="external">External</option></select></label>
      <label>批大小（0=配置默认）<input name="translation_batch_size" type="number" min="0" max="100" value="0"></label>
      <div class="checks"><label><input name="quality_check" type="checkbox"> 运行质量检查</label></div>
      <button id="submit" type="submit">上传并开始</button>
    </form><div id="message"></div>
  </section>
  <h2>任务</h2><section id="jobs" class="jobs"></section>
</main>
<script>
const form=document.querySelector('#job-form'), message=document.querySelector('#message'), jobs=document.querySelector('#jobs'), submit=document.querySelector('#submit');
const esc=s=>String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
function render(items){ jobs.innerHTML=items.length?'':'<div class="job">还没有任务。</div>'; for(const job of items){const p=job.progress||{}, links=(job.outputs||[]).map(x=>`<a href="${x.download_url}">${esc(x.name)}</a>`).join(''); const el=document.createElement('article'); el.className='job'; el.innerHTML=`<header><strong>${esc(job.filename)}</strong><span class="pill">${esc(job.status)}</span></header><div class="meta">${esc(job.id)} · 当前阶段 ${esc(p.active_stage)} · ${p.completed||0}/${p.total||0}</div><progress value="${p.percent||0}" max="100"></progress><div class="outputs">${links||'结果生成后会显示下载链接'}</div>${job.log_tail?`<details><summary>日志尾部</summary><pre>${esc(job.log_tail)}</pre></details>`:''}`; jobs.appendChild(el); }}
async function refresh(){try{const response=await fetch('/api/jobs'); render(await response.json())}catch(e){message.textContent='读取任务失败：'+e}}
form.addEventListener('submit',async event=>{event.preventDefault(); submit.disabled=true; message.textContent='正在上传…'; const data=new FormData(form); data.set('quality_check',form.quality_check.checked?'true':'false'); try{const response=await fetch('/api/jobs',{method:'POST',body:data}); const body=await response.json(); if(!response.ok)throw new Error(body.detail||response.statusText); message.textContent=`任务 ${body.id} 已启动`; form.reset(); await refresh()}catch(e){message.textContent='启动失败：'+e.message}finally{submit.disabled=false}});
refresh(); setInterval(refresh,3000);
</script></body></html>"""


def create_app(job_root: str | Path = DEFAULT_JOB_ROOT):
    """Create the FastAPI application; Web dependencies remain optional."""
    try:
        from fastapi import FastAPI, File, Form, HTTPException, UploadFile
        from fastapi.responses import FileResponse, HTMLResponse
    except ImportError as error:  # pragma: no cover - environment-specific guidance
        raise RuntimeError(
            "Web UI 依赖未安装，请运行：pip install -e .[web]"
        ) from error

    app = FastAPI(title="Anime Accurate Sub", version="0.1.0")
    manager = JobManager(job_root)
    app.state.job_manager = manager

    @app.get("/", response_class=HTMLResponse)
    def index():
        return INDEX_HTML

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/jobs")
    def list_jobs():
        return manager.list_jobs()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return manager.get_job(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="任务不存在") from error

    @app.post("/api/jobs", status_code=202)
    def create_job(
        video: UploadFile = File(...),
        backend: str = Form("sakura"),
        quality_check: bool = Form(False),
        translation_batch_size: int = Form(0),
    ):
        job_id = ""
        try:
            record, input_path = manager.create_job(
                video.filename or "",
                {
                    "backend": backend,
                    "quality_check": quality_check,
                    "translation_batch_size": translation_batch_size,
                },
            )
            job_id = record["id"]
            manager.save_upload(input_path, video.file)
            return manager.start_job(job_id)
        except (ValueError, FileNotFoundError) as error:
            if job_id:
                manager.fail_job(job_id, error)
            raise HTTPException(status_code=400, detail=str(error)) from error
        finally:
            video.file.close()

    @app.get("/api/jobs/{job_id}/files/{relative_path:path}")
    def download(job_id: str, relative_path: str):
        try:
            path = manager.downloadable_path(job_id, relative_path)
        except (KeyError, FileNotFoundError) as error:
            raise HTTPException(status_code=404, detail="结果文件不存在") from error
        return FileResponse(path, filename=path.name)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Anime Accurate Sub local Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--job-root", default=str(DEFAULT_JOB_ROOT))
    args = parser.parse_args()
    try:
        import uvicorn
    except ImportError as error:
        raise SystemExit("Web UI 依赖未安装，请运行：pip install -e .[web]") from error
    uvicorn.run(create_app(args.job_root), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
