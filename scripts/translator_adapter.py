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

import json, os, sys, time, argparse, urllib.request, urllib.error, abc, re, socket
from pathlib import Path
from typing import Optional, Sequence

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

DEFAULT_CONFIG = {
    "backend": "sakura",
    "sakura": {
        "model": "crosery/sakura-14b-qwen2.5-v1.0-q6k:latest",
        "host": "172.31.102.189",
        "timeout_s": 300,
        "max_retries": 4,
        "batch_size": 16,
        "num_ctx": 4096,
        "temperature": 0.1,
        "top_p": 0.3,
        "repeat_penalty": 1.0,
        "frequency_penalty": 0.1,
    },
    "qwen": {
        "model": "qwen2.5:7b",
        "host": "localhost",
    },
    "galtransl": {
        "model": "crosery/GalTransl-7B-v2.6:Q6_k",
        "host": "172.31.102.189",
        "timeout_s": 300,
        "max_retries": 4,
        "batch_size": 10,
        "num_ctx": 4096,
        "temperature": 0.2,
        "top_p": 0.8,
        "repeat_penalty": 1.1,
        "frequency_penalty": 0.1,
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
        self.series_info = ""

    @abc.abstractmethod
    def translate(self, text: str, context_before=None, context_after=None) -> str:
        """Translate Japanese text to Chinese."""
        pass

    def translate_batch(self, texts: Sequence[str], glossary_terms=None) -> list[str]:
        """Translate ordered lines, falling back to the single-line interface."""
        return [self.translate(text) for text in texts]

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
        self.host = str(backend_cfg.get("host", "localhost")).rstrip("/")
        if "://" in self.host:
            base_url = self.host
        elif re.search(r":\d+$", self.host):
            base_url = f"http://{self.host}"
        else:
            base_url = f"http://{self.host}:11434"
        self.api_url = f"{base_url}/api/chat"
        self.timeout_s = int(backend_cfg.get("timeout_s", 300))
        self.max_retries = int(backend_cfg.get("max_retries", 4))
        self.retry_backoff_s = float(backend_cfg.get("retry_backoff_s", 2.0))
        self.batch_size = int(backend_cfg.get("batch_size", 16))
        self.num_ctx = int(backend_cfg.get("num_ctx", 4096))
        self.temperature = float(backend_cfg.get("temperature", 0.1))
        self.top_p = float(backend_cfg.get("top_p", 0.3))
        self.repeat_penalty = float(backend_cfg.get("repeat_penalty", 1.0))
        self.frequency_penalty = float(backend_cfg.get("frequency_penalty", 0.1))

    def _call(self, messages, num_predict=1024):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "repeat_penalty": self.repeat_penalty,
                "num_predict": num_predict,
                "frequency_penalty": self.frequency_penalty,
                "num_ctx": self.num_ctx,
            },
            "keep_alive": "30m",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(
                self.api_url,
                data=data,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
                    result = json.loads(response.read().decode("utf-8"))
                content = result.get("message", {}).get("content", "").strip()
                if not content:
                    raise RuntimeError("Ollama returned an empty translation")
                return content
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
                json.JSONDecodeError,
                RuntimeError,
            ) as error:
                last_error = error
                if attempt >= self.max_retries:
                    break
                delay = min(self.retry_backoff_s * (2 ** (attempt - 1)), 20.0)
                print(
                    f"  Translation request failed ({attempt}/{self.max_retries}): "
                    f"{error}; retrying in {delay:.1f}s"
                )
                time.sleep(delay)
        raise RuntimeError(
            f"Ollama translation failed after {self.max_retries} attempts: {last_error}"
        )

    @staticmethod
    def _system_prompt(series_info: str = "") -> str:
        prompt = (
            "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成"
            "简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
        )
        if series_info:
            prompt += f"\n\n系列设定与角色信息：\n{series_info}"
        return prompt

    @staticmethod
    def _user_prompt(texts: Sequence[str], glossary_terms=None) -> str:
        raw_text = "\n".join(texts)
        terms = list(glossary_terms or [])
        if not terms:
            return f"将下面的日文文本翻译成中文：\n{raw_text}"
        glossary = "\n".join(f"{source}->{target}" for source, target in terms)
        return (
            "根据以下术语表（可以为空）：\n"
            f"{glossary}\n"
            "将下面的日文文本根据对应关系和备注翻译成中文：\n"
            f"{raw_text}"
        )

    @staticmethod
    def _parse_lines(raw: str, expected: int) -> list[str] | None:
        raw = raw.strip()
        raw = re.sub(r"^```(?:text|json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        if expected == 1:
            return [re.sub(r"\s+", " ", raw).strip()] if raw else None
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) == expected + 1 and lines[0].rstrip("：:") in {
            "翻译",
            "译文",
            "翻译结果",
        }:
            lines = lines[1:]
        if len(lines) != expected:
            return None
        if all(re.match(r"^\d+[.、]\s*", line) for line in lines):
            lines = [re.sub(r"^\d+[.、]\s*", "", line) for line in lines]
        return lines

    @staticmethod
    def _valid_translation(source: str, target: str) -> bool:
        if not target or target.startswith("[API Error"):
            return False
        if any(marker in target for marker in ("将下面", "术语表", "翻译结果如下")):
            return False
        nonverbal_source = bool(
            re.fullmatch(r"[\s\u30c3\u3063\u30fc\u2010-\u2015\-\u2026!\uff01?\uff1f\u3001\u3002\u30fb]+", source)
        )
        if (
            not re.search(r"[\u3400-\u9fffA-Za-z0-9]", target)
            and not nonverbal_source
        ):
            return False
        if len(target) > max(40, len(source) * 5):
            return False
        if re.search(r"(.)\1{15,}", target):
            return False
        has_kana = bool(re.search(r"[\u3040-\u30ff]", source))
        if has_kana and target.strip() == source.strip():
            return False
        return True

    def translate_batch(self, texts: Sequence[str], glossary_terms=None) -> list[str]:
        texts = [str(text).strip() for text in texts]
        if not texts:
            return []
        glossary_terms = self._matching_terms(texts, glossary_terms)
        messages = [
            {"role": "system", "content": self._system_prompt(self.series_info)},
            {"role": "user", "content": self._user_prompt(texts, glossary_terms)},
        ]
        raw = self._call(messages, num_predict=min(4096, max(512, len(texts) * 128)))
        translated = self._parse_lines(raw, len(texts))
        if translated and all(
            self._valid_translation(source, target)
            for source, target in zip(texts, translated)
        ):
            return translated

        if len(texts) == 1:
            raise RuntimeError(
                f"Sakura returned an invalid single-line translation: {raw[:200]}"
            )
        # A model may occasionally merge or drop a line. Recursively reduce the
        # batch instead of guessing which result belongs to which timestamp.
        middle = len(texts) // 2
        return self.translate_batch(texts[:middle], glossary_terms) + self.translate_batch(
            texts[middle:], glossary_terms
        )

    @staticmethod
    def _matching_terms(texts: Sequence[str], glossary_terms=None) -> list[tuple[str, str]]:
        joined = "\n".join(texts)
        return [
            (source, target)
            for source, target in (glossary_terms or [])
            if source in joined
        ]

    def translate(self, text, context_before=None, context_after=None):
        return self.translate_batch([text])[0]


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
