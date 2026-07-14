# S15.2: Hardware detection + smart default parameter recommendation
#
# Auto-detects GPU, VRAM, CPU cores and recommends optimal pipeline parameters:
#   - Translation model (Sakura-7B local vs Sakura-14B server)
#   - ASR batch size
#   - Parallel workers for batch processing
#   - Quality check level
#
# Usage:
#   python scripts/hardware.py
#   python scripts/hardware.py --json
#   python scripts/hardware.py --recommend

import json, os, sys, argparse, subprocess, platform
from pathlib import Path
from typing import Optional

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


class HardwareDetector:
    """Detect hardware specs and recommend optimal parameters."""

    def __init__(self):
        self.info = self._detect_all()

    def _detect_all(self) -> dict:
        return {
            "platform": self._detect_platform(),
            "cpu": self._detect_cpu(),
            "gpu": self._detect_gpu(),
            "memory": self._detect_memory(),
        }

    def _detect_platform(self) -> dict:
        return {
            "system": platform.system(),
            "release": platform.release(),
            "python": sys.version.split()[0],
        }

    def _detect_cpu(self) -> dict:
        try:
            import psutil
            cpu_count = psutil.cpu_count(logical=True)
            cpu_phys = psutil.cpu_count(logical=False)
            return {"logical_cores": cpu_count, "physical_cores": cpu_phys}
        except ImportError:
            return {"logical_cores": os.cpu_count() or 4, "physical_cores": None}

    def _detect_gpu(self) -> dict:
        """Detect NVIDIA GPU via nvidia-smi."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if lines and lines[0]:
                    parts = [p.strip() for p in lines[0].split(",")]
                    total_mb = self._parse_memory(parts[1]) if len(parts) > 1 else 0
                    free_mb = self._parse_memory(parts[2]) if len(parts) > 2 else 0
                    return {
                        "available": True,
                        "name": parts[0] if len(parts) > 0 else "Unknown",
                        "vram_total_mb": total_mb,
                        "vram_free_mb": free_mb,
                        "driver_version": parts[3] if len(parts) > 3 else "",
                    }
        except (FileNotFoundError, subprocess.TimeoutExpired, IndexError):
            pass

        # Check PyTorch CUDA as fallback
        try:
            import torch
            if torch.cuda.is_available():
                return {
                    "available": True,
                    "name": torch.cuda.get_device_name(0),
                    "vram_total_mb": int(torch.cuda.get_device_properties(0).total_memory / 1024 / 1024),
                    "vram_free_mb": None,  # Can't easily get free
                    "driver_version": "",
                }
        except ImportError:
            pass

        return {"available": False, "name": "No GPU detected"}

    def _detect_memory(self) -> dict:
        try:
            import psutil
            mem = psutil.virtual_memory()
            return {"total_gb": round(mem.total / (1024**3), 1), "available_gb": round(mem.available / (1024**3), 1)}
        except ImportError:
            return {"total_gb": None, "available_gb": None}

    def _parse_memory(self, text: str) -> int:
        text = text.strip().lower()
        if "mib" in text:
            return int(text.replace("mib", "").strip())
        return 0

    def recommend(self) -> dict:
        """Recommend optimal pipeline parameters based on detected hardware."""
        gpu = self.info["gpu"]
        cpu = self.info["cpu"]
        mem = self.info["memory"]
        vram = gpu.get("vram_total_mb", 0) if gpu.get("available") else 0

        # Model recommendation
        if vram >= 16000:
            model = "sakura-14b"
            model_name = "crosery/sakura-14b-qwen2.5-v1.0-q6k:latest"
            host = "localhost"
            reason = "VRAM >= 16GB, can run Sakura-14B"
        elif vram >= 8000:
            model = "sakura-7b"
            model_name = "EasonONLINE/Sakura-qwen2.5-v1.0:7b"
            host = "localhost"
            reason = "VRAM >= 8GB, can run Sakura-7B"
        elif vram >= 4000:
            model = "galtransl"
            model_name = "crosery/GalTransl-7B-v2.6:IQ4_XS"
            host = "localhost"
            reason = "VRAM >= 4GB, use GalTransl-7B (smaller)"
        else:
            model = "sakura-14b"
            model_name = "crosery/sakura-14b-qwen2.5-v1.0-q6k:latest"
            host = "172.31.102.189"
            reason = f"VRAM {vram}MB insufficient, use server"

        # ASR batch size based on VRAM
        if vram >= 12000:
            asr_batch = 8
        elif vram >= 8000:
            asr_batch = 4
        elif vram >= 4000:
            asr_batch = 2
        else:
            asr_batch = 1

        # Parallel workers
        cpu_cores = cpu.get("logical_cores") or 4
        parallel_workers = max(1, min(cpu_cores // 2, 4))

        # Enable quality check?
        enable_qc = vram >= 12000

        return {
            "hardware": {
                "gpu": gpu.get("name", "None"),
                "vram_mb": vram,
                "cpu_cores": cpu_cores,
                "ram_gb": mem.get("total_gb", 0),
            },
            "recommendations": {
                "translation": {
                    "backend": model,
                    "model": model_name,
                    "host": host,
                    "reason": reason,
                },
                "asr": {
                    "batch_size": asr_batch,
                    "reason": f"Based on {vram}MB VRAM",
                },
                "parallel": {
                    "workers": parallel_workers,
                    "reason": f"Based on {cpu_cores} CPU cores",
                },
                "quality_check": {
                    "enabled": enable_qc,
                    "reason": f"VRAM {'>=' if enable_qc else '<'} 12GB",
                },
            },
        }

    def summary(self) -> str:
        """Print human-readable summary."""
        info = self.info
        gpu = info["gpu"]
        cpu = info["cpu"]
        rec = self.recommend()

        lines = []
        lines.append("=" * 60)
        lines.append("HARDWARE DETECTION")
        lines.append("=" * 60)
        lines.append(f"  Platform: {info['platform']['system']} {info['platform']['release']}")
        lines.append(f"  Python: {info['platform']['python']}")
        lines.append(f"  CPU: {cpu.get('logical_cores', '?')} logical cores")

        if gpu.get("available"):
            lines.append(f"  GPU: {gpu['name']}")
            lines.append(f"  VRAM: {gpu.get('vram_total_mb', 0)} MB total / {gpu.get('vram_free_mb', '?')} MB free")
        else:
            lines.append(f"  GPU: None (CPU mode)")

        if info["memory"].get("total_gb"):
            lines.append(f"  RAM: {info['memory']['total_gb']} GB")

        lines.append("")
        lines.append("=" * 60)
        lines.append("RECOMMENDED PARAMETERS")
        lines.append("=" * 60)
        t = rec["recommendations"]["translation"]
        lines.append(f"  Translation: {t['backend']} ({t['model']})")
        lines.append(f"    Host: {t['host']}")
        lines.append(f"    Reason: {t['reason']}")
        lines.append(f"  ASR batch: {rec['recommendations']['asr']['batch_size']}")
        lines.append(f"  Parallel workers: {rec['recommendations']['parallel']['workers']}")
        lines.append(f"  Quality check: {'enabled' if rec['recommendations']['quality_check']['enabled'] else 'disabled'}")

        return "\n".join(lines)


# ============ Evaluate ============

def evaluate():
    print("\n============================================================")
    print("S15.2 SMART DEFAULTS EVALUATION")
    print("============================================================")

    detector = HardwareDetector()
    print(detector.summary())

    rec = detector.recommend()
    print(f"\n  JSON output available with --json")
    assert "recommendations" in rec
    assert "translation" in rec["recommendations"]
    assert "asr" in rec["recommendations"]
    print("\n  All assertions passed!")

    print("\n============================================================")
    print("EVALUATION COMPLETE")
    print("============================================================")


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(description="S15.2 Hardware Detection")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--recommend", action="store_true", help="Show recommendations only")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return

    detector = HardwareDetector()

    if args.json:
        print(json.dumps(detector.recommend(), ensure_ascii=False, indent=2))
        return

    if args.recommend:
        rec = detector.recommend()
        for category, params in rec["recommendations"].items():
            print(f"[{category}]")
            for k, v in params.items():
                print(f"  {k}: {v}")
            print()
        return

    print(detector.summary())


if __name__ == "__main__":
    main()