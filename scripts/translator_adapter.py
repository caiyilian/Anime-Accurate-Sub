# S14.1: Translator Adapter - abstract base + multi-backend implementations
#
# Architecture:
#   TranslatorAdapter (ABC)
#     +-- SakuraAdapter      (Ollama Sakura-7B/14B)
#     +-- QwenAdapter        (Ollama Qwen2.5)
#     +-- GalTranslAdapter   (Ollama GalTransl-7B)
#     +-- ExternalAdapter    (OpenAI-compatible API)
#
# Config file format:
#   {
#     "backend": "sakura",
#     "sakura": {"model": "crosery/sakura-14b-qwen2.5-v1.0-q6k:latest", "host": "172.31.102.189"},
#     "qwen": {"model": "qwen2.5:7b", "host": "localhost"},
#     "galtransl": {"model": "crosery/GalTransl-7B-v2.6:Q6_k", "host": "172.31.102.189"},
#     "external": {"api_url": "...", "api_key": "...", "model": "..."}
#   }
#
# Usage:
#   python scripts/translator_adapter.py --text "おはよう" --backend sakura
#   python scripts/translator_adapter.py --text "おはよう" --config translator_config.json
#   python scripts/translator_adapter.py --list-backends
#   python scripts/translator_adapter.py --evaluate

import json, os, sys, time, argparse, urllib.request, abc
from pathlib import Path
from typing import Optional

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

DEFAULT_CONFIG = {
    "backend": "sakura",
    "sakura": {
        "model": "crosery/sakura-14b-qwen2.5-v1.0-q6k:latest",
        "host": "172.31.102.189",
    },
    "qwen": {
        "model": "qwen2.5:7b",
        "host": "localhost",
    },
    "galtransl": {
        "model": "crosery/GalTransl-7B-v2.6:Q6_k",
        "host": "172.31.102.189",
    },
    "external": {
        "api_url": "",
        "api_key": "",
        "model": "",
    },
}


# ============ Abstract Base ============

class TranslatorAdapter(abc.ABC):
    """Abstract base class for all translation backends."""

    def __init__(self, config: dict):
        self.config = config

    @abc.abstractmethod
    def translate(self, text: str, context_before=None, context_after=None) -> str:
        """Translate Japanese text to Chinese."""
        pass

    @abc.abstractmethod
    def name(self) -> str:
        """Return backend name for display."""
        pass

    @classmethod
    def from_config(cls, config: dict) -> "TranslatorAdapter":
        """Factory: create adapter from config."""
        backend = config.get("backend", "sakura")
        adapters = {
            "sakura": SakuraAdapter,
            "qwen": QwenAdapter,
            "galtransl": GalTranslAdapter,
            "external": ExternalAdapter,
        }
        adapter_cls = adapters.get(backend)
        if not adapter_cls:
            raise ValueError(f"Unknown backend: {backend}. Available: {list(adapters.keys())}")
        return adapter_cls(config)


# ============ Ollama Base ============

class OllamaAdapter(TranslatorAdapter):
    """Base for Ollama-based adapters."""

    def __init__(self, config: dict, backend_key: str):
        super().__init__(config)
        backend_cfg = config.get(backend_key, {})
        self.model = backend_cfg.get("model", "")
        self.host = backend_cfg.get("host", "localhost")
        self.api_url = f"http://{self.host}:11434/api/chat"

    def _call(self, messages, temperature=0.1):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": 512},
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.api_url, data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("message", {}).get("content", "").strip()

    def translate(self, text, context_before=None, context_after=None):
        messages = [
            {"role": "system", "content": "你是一个轻小说翻译模型，可以将日语翻译成中文。"},
            {"role": "user", "content": f"将下面的日语文本翻译成中文：{text}"},
        ]
        return self._call(messages)


# ============ Sakura ============

class SakuraAdapter(OllamaAdapter):
    def __init__(self, config: dict):
        super().__init__(config, "sakura")

    def name(self):
        return f"Sakura ({self.model})"


# ============ Qwen ============

class QwenAdapter(OllamaAdapter):
    def __init__(self, config: dict):
        super().__init__(config, "qwen")

    def name(self):
        return f"Qwen ({self.model})"


# ============ GalTransl ============

class GalTranslAdapter(OllamaAdapter):
    def __init__(self, config: dict):
        super().__init__(config, "galtransl")

    def name(self):
        return f"GalTransl ({self.model})"


# ============ External API ============

class ExternalAdapter(TranslatorAdapter):
    """OpenAI-compatible API adapter."""

    def __init__(self, config: dict):
        super().__init__(config)
        ext = config.get("external", {})
        self.api_url = ext.get("api_url", "")
        self.api_key = ext.get("api_key", "")
        self.model = ext.get("model", "")

    def name(self):
        return f"External ({self.model})"

    def translate(self, text, context_before=None, context_after=None):
        if not self.api_url:
            return "[External API not configured]"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一个轻小说翻译模型，可以将日语翻译成中文。"},
                {"role": "user", "content": f"将下面的日语文本翻译成中文：{text}"},
            ],
            "temperature": 0.1,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.api_url, data=data, headers=headers,
        )
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            return f"[API Error: {e}]"


# ============ Config ============

def load_config(path: str = "") -> dict:
    """Load translator config from file, or return default."""
    if path:
        config_path = Path(path)
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
    return dict(DEFAULT_CONFIG)


def save_default_config(path: str = "translator_config.json"):
    """Save default config to file."""
    config_path = Path(path)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    print(f"Default config saved: {path}")


# ============ Evaluate ============

def evaluate():
    print("\n============================================================")
    print("S14.1 TRANSLATOR ADAPTER EVALUATION")
    print("============================================================")

    config = load_config()

    test_texts = [
        "おはよう、唯",
        "今日も元気だね",
        "澪ちゃん、一緒に練習しない？",
    ]

    backends_to_test = ["sakura", "qwen", "galtransl"]
    results = {}

    for backend_name in backends_to_test:
        cfg = dict(config)
        cfg["backend"] = backend_name
        try:
            adapter = TranslatorAdapter.from_config(cfg)
            print(f"\n--- Backend: {adapter.name()} ---")

            backend_results = []
            for text in test_texts:
                t0 = time.time()
                try:
                    result = adapter.translate(text)
                    elapsed = time.time() - t0
                except Exception as e:
                    result = f"[ERROR: {e}]"
                    elapsed = time.time() - t0
                backend_results.append({
                    "ja": text,
                    "zh": result,
                    "time_s": round(elapsed, 2),
                })
                print(f"  {text[:20]} -> {result[:30]} ({elapsed:.1f}s)")

            results[backend_name] = {
                "name": adapter.name(),
                "samples": backend_results,
            }
        except Exception as e:
            print(f"  SKIP: {e}")
            results[backend_name] = {"name": backend_name, "error": str(e)}

    # Save
    out_path = project_root / "docs" / "evaluation" / "S14.1_adapter_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "config": {k: v for k, v in config.items() if k != "external"},
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved: {out_path}")

    print("\n============================================================")
    print("EVALUATION COMPLETE")
    print("============================================================")


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(description="S14.1 Translator Adapter")
    parser.add_argument("--text", type=str, help="Japanese text to translate")
    parser.add_argument("--backend", type=str, choices=["sakura", "qwen", "galtransl", "external"],
                        help="Translation backend")
    parser.add_argument("--config", type=str, default="", help="Config file path")
    parser.add_argument("--list-backends", action="store_true", help="List available backends")
    parser.add_argument("--save-config", type=str, help="Save default config to file")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.list_backends:
        print("Available backends:")
        print("  sakura    - Sakura-7B/14B (Ollama)")
        print("  qwen      - Qwen2.5 (Ollama)")
        print("  galtransl - GalTransl-7B (Ollama)")
        print("  external  - OpenAI-compatible API")
        return

    if args.save_config:
        save_default_config(args.save_config)
        return

    if args.evaluate:
        evaluate()
        return

    if args.text:
        config = load_config(args.config)
        if args.backend:
            config["backend"] = args.backend
        adapter = TranslatorAdapter.from_config(config)
        result = adapter.translate(args.text)
        print(result)
        return

    parser.print_help()


if __name__ == "__main__":
    main()