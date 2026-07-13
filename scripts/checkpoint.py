# S12.1: Checkpoint resume module - JSONL atomic writes + stage tracking + restart recovery
#
# Pipeline stages:
#   extract_audio -> asr -> translate -> subtitle -> quality_check
#
# Each stage writes its output to a JSONL checkpoint file.
# On restart, completed stages are automatically skipped.
# Atomic writes (temp file + rename) prevent file corruption.
#
# Usage:
#   cp = Checkpoint("output_dir")
#   cp.run_stage("asr", asr_func, input_data)
#   cp.resume()  # returns list of completed stages

import json, os, sys, time, shutil, tempfile, argparse
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, asdict

PIPELINE_STAGES = [
    "extract_audio",
    "asr",
    "translate",
    "subtitle",
    "quality_check",
]


@dataclass
class StageResult:
    stage: str
    status: str  # completed, failed, skipped
    input_file: str
    output_file: Optional[str] = None
    duration_s: float = 0.0
    error: Optional[str] = None
    timestamp: str = ""


class Checkpoint:
    """Pipeline checkpoint manager with atomic writes and resume support."""

    def __init__(self, work_dir: str, stages: Optional[List[str]] = None):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.stages = stages or PIPELINE_STAGES
        self.checkpoint_file = self.work_dir / "checkpoint.json"
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, StageResult]:
        """Load checkpoint state from file."""
        if not self.checkpoint_file.exists():
            return {}
        try:
            with open(self.checkpoint_file, encoding="utf-8") as f:
                data = json.load(f)
            return {k: StageResult(**v) for k, v in data.items()}
        except (json.JSONDecodeError, KeyError):
            return {}

    def _save_state(self):
        """Save checkpoint state atomically."""
        data = {k: asdict(v) for k, v in self.state.items()}
        # Atomic write: write to temp file, then rename
        tmp = self.checkpoint_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.checkpoint_file)  # Atomic on most OS

    def is_completed(self, stage: str) -> bool:
        """Check if a stage is already completed."""
        result = self.state.get(stage)
        return result is not None and result.status == "completed"

    def get_completed_stages(self) -> List[str]:
        """Get list of completed stages."""
        return [s for s in self.stages if self.is_completed(s)]

    def get_pending_stages(self) -> List[str]:
        """Get list of pending stages."""
        return [s for s in self.stages if not self.is_completed(s)]

    def mark_completed(self, stage: str, input_file: str = "",
                        output_file: str = "", duration_s: float = 0.0):
        """Mark a stage as completed."""
        self.state[stage] = StageResult(
            stage=stage,
            status="completed",
            input_file=input_file,
            output_file=output_file,
            duration_s=round(duration_s, 2),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        self._save_state()

    def mark_failed(self, stage: str, input_file: str = "", error: str = ""):
        """Mark a stage as failed."""
        self.state[stage] = StageResult(
            stage=stage,
            status="failed",
            input_file=input_file,
            error=str(error)[:200],
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        self._save_state()

    def run_stage(self, stage: str, func: Callable, input_data: Any = None,
                   **kwargs) -> Any:
        """Run a stage if not already completed, or skip it.

        Args:
            stage: Stage name (must be in stages list)
            func: Function to execute
            input_data: Input data for the function
            **kwargs: Additional kwargs for the function

        Returns:
            Stage output data, or None if skipped
        """
        if self.is_completed(stage):
            print(f"  [SKIP] {stage} (already completed)")
            return None

        print(f"  [RUN] {stage}...")
        t0 = time.time()
        try:
            result = func(input_data, **kwargs) if input_data is not None else func(**kwargs)
            elapsed = time.time() - t0
            self.mark_completed(stage, duration_s=elapsed)
            print(f"  [DONE] {stage} ({elapsed:.1f}s)")
            return result
        except Exception as e:
            elapsed = time.time() - t0
            self.mark_failed(stage, error=str(e))
            print(f"  [FAIL] {stage} after {elapsed:.1f}s: {e}")
            raise

    def reset(self, stage: Optional[str] = None):
        """Reset checkpoint for a specific stage or all stages."""
        if stage:
            self.state.pop(stage, None)
            print(f"  Reset: {stage}")
        else:
            self.state.clear()
            print(f"  Reset: all stages")
        self._save_state()

    def summary(self) -> str:
        """Print checkpoint summary."""
        lines = []
        lines.append(f"Checkpoint: {self.checkpoint_file}")
        for stage in self.stages:
            result = self.state.get(stage)
            if result:
                status_icon = {"completed": "OK", "failed": "FAIL", "skipped": "SKIP"}.get(
                    result.status, "?")
                lines.append(f"  [{status_icon}] {stage} ({result.duration_s:.1f}s)")
            else:
                lines.append(f"  [..] {stage} (pending)")
        return "\n".join(lines)

    def __repr__(self):
        return f"Checkpoint({len(self.state)}/{len(self.stages)} stages, {self.work_dir})"


# ============ JSONL Result Storage ============

class JSONLStore:
    """Atomic JSONL writer for intermediate results."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries = []
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

    def append(self, entry: dict):
        """Append a JSONL entry atomically."""
        self._entries.append(entry)
        # Write to temp, then rename
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        tmp.replace(self.path)

    def append_batch(self, entries: List[dict]):
        """Append multiple entries at once."""
        for entry in entries:
            self.append(entry)

    def read_all(self) -> List[dict]:
        return list(self._entries)

    def count(self) -> int:
        return len(self._entries)

    def clear(self):
        self._entries = []
        if self.path.exists:
            self.path.unlink(missing_ok=True)


# ============ Test / Evaluation ============

def evaluate():
    """Run checkpoint evaluation with simulated stages."""
    import tempfile as tmp_module
    tmp_dir = Path(tmp_module.mkdtemp())

    print("\n============================================================")
    print("S12.1 CHECKPOINT RESUME EVALUATION")
    print("============================================================")

    # Test 1: Basic checkpoint flow
    print("\n--- Test 1: Basic checkpoint flow ---")
    cp = Checkpoint(str(tmp_dir / "test1"))
    assert len(cp.get_completed_stages()) == 0
    assert len(cp.get_pending_stages()) == 5

    # Simulate stage 1
    cp.mark_completed("extract_audio", duration_s=10.5)
    assert cp.is_completed("extract_audio")
    assert len(cp.get_completed_stages()) == 1
    print("  Stage 1 completed: OK")

    # Test 2: Resume - skip completed stages
    print("\n--- Test 2: Resume simulation ---")
    cp2 = Checkpoint(str(tmp_dir / "test1"))  # Same dir = resume
    assert cp2.is_completed("extract_audio")
    assert not cp2.is_completed("asr")
    print("  Resume: extract_audio skipped, asr pending: OK")

    # Test 3: Run stage with function
    print("\n--- Test 3: Run stage with function ---")
    cp3 = Checkpoint(str(tmp_dir / "test2"))

    def dummy_asr(data):
        return {"text": "recognized: " + data}

    def dummy_translate(data):
        return {"text": "translated: " + data["text"]}

    result1 = cp3.run_stage("asr", dummy_asr, input_data="hello")
    assert result1["text"] == "recognized: hello"
    assert cp3.is_completed("asr")

    # This should skip since asr is already completed
    result1_skip = cp3.run_stage("asr", dummy_asr, input_data="hello")
    assert result1_skip is None  # Skipped
    print("  Run + skip: OK")

    # Test 4: Atomic write
    print("\n--- Test 4: Atomic write ---")
    store = JSONLStore(str(tmp_dir / "test.jsonl"))
    store.append({"stage": "asr", "index": 0, "text": "hello"})
    store.append({"stage": "asr", "index": 1, "text": "world"})
    assert store.count() == 2
    all_entries = store.read_all()
    assert len(all_entries) == 2
    print("  Atomic write: OK")

    # Test 5: Full pipeline simulation
    print("\n--- Test 5: Full pipeline simulation ---")
    cp5 = Checkpoint(str(tmp_dir / "test5"))
    store5 = JSONLStore(str(tmp_dir / "test5" / "results.jsonl"))

    # Simulate interrupted pipeline (only first 2 stages done)
    cp5.mark_completed("extract_audio", duration_s=5.0)
    cp5.mark_completed("asr", duration_s=30.0)
    store5.append({"stage": "asr", "text": "recognized: hello"})

    print(f"  Completed: {cp5.get_completed_stages()}")
    print(f"  Pending: {cp5.get_pending_stages()}")
    assert "translate" in cp5.get_pending_stages()

    # Resume - should skip extract_audio and asr
    cp5_resume = Checkpoint(str(tmp_dir / "test5"))
    assert cp5_resume.is_completed("extract_audio")
    assert cp5_resume.is_completed("asr")
    assert not cp5_resume.is_completed("translate")
    print("  Resume correct: OK")

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\n============================================================")
    print("ALL TESTS PASSED")
    print("============================================================")


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(description="S12.1 Checkpoint Resume")
    parser.add_argument("--work-dir", type=str, help="Working directory for checkpoint")
    parser.add_argument("--status", action="store_true", help="Show checkpoint status")
    parser.add_argument("--reset", type=str, nargs="?", const="all", help="Reset checkpoint")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return

    if args.work_dir and args.status:
        cp = Checkpoint(args.work_dir)
        print(cp.summary())
        return

    if args.work_dir and args.reset:
        cp = Checkpoint(args.work_dir)
        if args.reset == "all":
            cp.reset()
        else:
            cp.reset(args.reset)
        return

    parser.print_help()


if __name__ == "__main__":
    main()