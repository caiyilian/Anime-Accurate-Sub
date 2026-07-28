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

import abc
import argparse
import inspect
import json
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from scripts.plugin_system import load_plugins, plugin_registry  # noqa: E402

DEFAULT_CONFIG = {
    "backend": "sakura",
    "sakura": {
        "model": "crosery/sakura-14b-qwen2.5-v1.0-q6k:latest",
        "host": "172.31.102.189",
        "timeout_s": 300,
        "max_retries": 4,
        "validation_retries": 2,
        "validation_fallback_backend": "galtransl",
        "validation_rescue_models": [
            "sensenova-6.7-flash-lite",
            "deepseek-v4-flash",
        ],
        "validation_rescue_base_url": "https://token.sensenova.cn/v1",
        "validation_rescue_api_key_file": "config/sensenova_apikeys",
        "validation_rescue_attempts": 2,
        "validation_quarantine_on_failure": True,
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


def _call_batch_with_optional_context(
    adapter,
    texts,
    glossary_terms,
    context_before=None,
    context_after=None,
):
    """Call old and new translator plugins without masking adapter errors."""
    method = adapter.translate_batch
    try:
        parameters = inspect.signature(method).parameters.values()
        supports_keywords = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        parameter_names = {parameter.name for parameter in parameters}
    except (TypeError, ValueError):
        supports_keywords = False
        parameter_names = set()
    if supports_keywords or {"context_before", "context_after"} <= parameter_names:
        return method(
            texts,
            glossary_terms,
            context_before=context_before,
            context_after=context_after,
        )
    return method(texts, glossary_terms)


# ============ Abstract Base ============

class TranslatorAdapter(abc.ABC):
    """Abstract base class for all translation backends."""

    def __init__(self, config: dict):
        self.config = config
        self.series_info = ""
        self._translation_models: dict[str, str] = {}
        self._translation_fallbacks: dict[str, bool] = {}
        self._translation_errors: dict[str, str] = {}

    @abc.abstractmethod
    def translate(self, text: str, context_before=None, context_after=None) -> str:
        """Translate Japanese text to Chinese."""
        pass

    def translate_batch(
        self,
        texts: Sequence[str],
        glossary_terms=None,
        context_before=None,
        context_after=None,
    ) -> list[str]:
        """Translate ordered lines, falling back to the single-line interface."""
        texts = list(texts)
        outer_before = list(context_before or [])
        outer_after = list(context_after or [])
        return [
            self.translate(
                text,
                context_before=outer_before + texts[:index],
                context_after=texts[index + 1:] + outer_after,
            )
            for index, text in enumerate(texts)
        ]

    def result_model(self, source: str) -> str:
        """Return the model that produced a source line's latest translation."""
        return self._translation_models.get(
            source,
            getattr(self, "model", self.name()),
        )

    def result_is_fallback(self, source: str) -> bool:
        return self._translation_fallbacks.get(source, False)

    def result_error(self, source: str) -> str | None:
        """Return a terminal recovery error when a line was quarantined."""
        return self._translation_errors.get(source)

    @abc.abstractmethod
    def name(self) -> str:
        """Return backend name for display."""
        pass

    @classmethod
    def from_config(cls, config: dict) -> "TranslatorAdapter":
        """Factory: create adapter from config."""
        _ensure_builtin_translator_plugins()
        backend = str(config.get("backend", "sakura")).lower()
        return plugin_registry.create("translator", backend, config)


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
        self.validation_retries = int(backend_cfg.get("validation_retries", 2))

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
    def _user_prompt(
        texts: Sequence[str],
        glossary_terms=None,
    ) -> str:
        raw_text = "\n".join(texts)
        terms = list(glossary_terms or [])
        if not terms:
            return f"将下面的待翻译日文逐行翻译成中文：\n{raw_text}"
        glossary = "\n".join(f"{source}->{target}" for source, target in terms)
        return (
            "根据以下术语表（可以为空）：\n"
            f"{glossary}\n"
            "将下面的待翻译日文根据对应关系和备注逐行翻译成中文：\n"
            f"{raw_text}"
        )

    @staticmethod
    def _context_block(context_before=None, context_after=None) -> str:
        parts = []
        if context_before:
            parts.append("已翻译前文（简体中文）：\n" + "\n".join(context_before))
        if context_after:
            parts.append("参考下文：\n" + "\n".join(context_after))
        if not parts:
            return ""
        return (
            "\n\n参考对话（只供理解待翻译句子的指代、语气和省略信息，"
            "禁止翻译、复述或输出）：\n"
            + "\n".join(parts)
            + "\n只输出 user 消息中待翻译日文的简体中文译文。"
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
    def _tagged_texts(texts: Sequence[str]) -> list[str]:
        """Attach stable IDs so a model cannot silently swap batch lines."""
        return [f"[[L{index:03d}]] {text}" for index, text in enumerate(texts)]

    @staticmethod
    def _parse_tagged_lines(raw: str, expected: int) -> list[str] | None:
        """Parse tagged translations, accepting brackets commonly normalized by LLMs."""
        raw = raw.strip()
        raw = re.sub(r"^```(?:text|json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        tagged = {}
        pattern = re.compile(
            r"^\s*(?:\[\[|\[|【)\s*L(\d{1,4})\s*(?:\]\]|\]|】)\s*(.*?)\s*$"
        )
        for line in raw.splitlines():
            if not line.strip():
                continue
            match = pattern.match(line)
            if not match:
                return None
            index = int(match.group(1))
            target = match.group(2).strip()
            if index >= expected or index in tagged or not target:
                return None
            tagged[index] = target
        if set(tagged) != set(range(expected)):
            return None
        return [tagged[index] for index in range(expected)]

    @staticmethod
    def _is_nonverbal_source(source: str) -> bool:
        """Return whether a cue contains only vocal markers and punctuation."""
        vocal_markers = {"っ", "ッ", "ー"}
        return bool(source) and all(
            character in vocal_markers
            or unicodedata.category(character)[0] in {"P", "S", "Z"}
            for character in source
        )

    @staticmethod
    def _valid_translation(source: str, target: str) -> bool:
        if not target or target.startswith("[API Error"):
            return False
        if any(
            marker in target
            for marker in (
                "将下面",
                "术语表",
                "翻译结果如下",
                "上文：",
                "上文:",
                "下文：",
                "下文:",
                "参考对话",
                "只供理解",
                "只输出 user 消息",
                "待翻译日文的简体中文译文",
            )
        ):
            return False
        nonverbal_source = OllamaAdapter._is_nonverbal_source(source)
        if (
            not re.search(r"[\u3400-\u9fffA-Za-z0-9]", target)
            and not nonverbal_source
        ):
            return False
        if len(target) > max(40, len(source) * 5):
            return False
        if re.search(r"(.)\1{15,}", target):
            return False
        if OllamaAdapter._has_suspicious_repeated_phrase(source, target):
            return False
        has_kana = bool(re.search(r"[\u3040-\u30ff]", source))
        if has_kana and target.strip() == source.strip():
            return False
        return True

    @staticmethod
    def _has_suspicious_repeated_phrase(source: str, target: str) -> bool:
        """Detect three merged neighboring lines with a repeated Chinese lead-in."""
        compact_target = re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", target)
        compact_source = re.sub(r"\s+", "", source)
        source_has_triplet = bool(re.search(r"(.{1,4})\1\1", compact_source))
        if source_has_triplet:
            return False
        for size in range(8, 2, -1):
            for start in range(0, max(0, len(compact_target) - size + 1)):
                phrase = compact_target[start:start + size]
                if compact_target.count(phrase) >= 3:
                    return True
        return False

    def translate_batch(
        self,
        texts: Sequence[str],
        glossary_terms=None,
        context_before=None,
        context_after=None,
    ) -> list[str]:
        texts = [str(text).strip() for text in texts]
        if not texts:
            return []
        glossary_terms = self._matching_terms(texts, glossary_terms)
        context_enabled = context_before is not None or context_after is not None
        if context_enabled and len(texts) > 1:
            translated = []
            outer_before = list(context_before or [])
            outer_after = list(context_after or [])
            for index, text in enumerate(texts):
                translated.extend(
                    self.translate_batch(
                        [text],
                        self._matching_terms([text], glossary_terms),
                        context_before=outer_before + texts[:index],
                        context_after=texts[index + 1:] + outer_after,
                    )
                )
            return translated
        tagged_batch = len(texts) > 1
        prompt_texts = self._tagged_texts(texts) if tagged_batch else texts
        system_prompt = self._system_prompt(self.series_info) + self._context_block(
            context_before,
            context_after,
        )
        if tagged_batch:
            system_prompt += (
                "\n逐行翻译。每行开头的 [[Lnnn]] 是不可翻译的行号；译文必须保留"
                "相同行号，不得交换、合并或遗漏。"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": self._user_prompt(prompt_texts, glossary_terms),
            },
        ]
        try:
            raw = self._call(
                messages,
                num_predict=min(4096, max(512, len(texts) * 128)),
            )
        except Exception as error:
            if len(texts) == 1:
                return [
                    self._fallback_invalid_single(
                        texts[0],
                        glossary_terms,
                        f"primary translation request failed: {error}",
                        context_before=context_before,
                        context_after=context_after,
                    )
                ]
            # A batch-level transport failure may be request-size-specific. Split
            # it before allowing each individual line to use its fallback chain.
            middle = len(texts) // 2
            return self.translate_batch(
                texts[:middle],
                glossary_terms,
                context_before=context_before,
                context_after=texts[middle:] + list(context_after or []),
            ) + self.translate_batch(
                texts[middle:],
                glossary_terms,
                context_before=list(context_before or []) + texts[:middle],
                context_after=context_after,
            )
        translated = (
            self._parse_tagged_lines(raw, len(texts))
            if tagged_batch
            else self._parse_lines(raw, len(texts))
        )
        if translated and all(
            self._valid_translation(source, target)
            for source, target in zip(texts, translated)
        ):
            for source in texts:
                self._translation_models[source] = self.model
                self._translation_fallbacks[source] = False
            return translated

        if len(texts) == 1:
            return [
                self._recover_invalid_single(
                    texts[0],
                    glossary_terms,
                    raw,
                    context_before=context_before,
                    context_after=context_after,
                )
            ]
        # A model may occasionally merge or drop a line. Recursively reduce the
        # batch instead of guessing which result belongs to which timestamp.
        middle = len(texts) // 2
        return self.translate_batch(
            texts[:middle],
            glossary_terms,
            context_before=context_before,
            context_after=texts[middle:] + list(context_after or []),
        ) + self.translate_batch(
            texts[middle:],
            glossary_terms,
            context_before=list(context_before or []) + texts[:middle],
            context_after=context_after,
        )

    def _recover_invalid_single(
        self,
        source: str,
        glossary_terms,
        raw: str,
        context_before=None,
        context_after=None,
    ) -> str:
        """Retry a rejected line with a constrained prompt before using a fallback."""
        last_raw = raw
        for attempt in range(1, self.validation_retries + 1):
            messages = [
                {
                    "role": "system",
                    "content": (
                        self._system_prompt(self.series_info)
                        + self._context_block(context_before, context_after)
                        + "\n只输出一行简洁的简体中文译文；禁止解释、重复、引号包裹和遗漏。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "上一次译文未通过字幕校验。请重新翻译且只输出一行：\n"
                        + self._user_prompt([source], glossary_terms)
                    ),
                },
            ]
            try:
                last_raw = self._call(messages, num_predict=256)
            except Exception as error:
                last_raw = (
                    f"validation retry {attempt}/{self.validation_retries} "
                    f"request failed: {error}"
                )
                print(f"  Translation {last_raw}")
                break
            parsed = self._parse_lines(last_raw, 1)
            if parsed and self._valid_translation(source, parsed[0]):
                self._translation_models[source] = self.model
                self._translation_fallbacks[source] = False
                print(
                    f"  Translation validation recovered on retry "
                    f"{attempt}/{self.validation_retries}"
                )
                return parsed[0]
        return self._fallback_invalid_single(
            source,
            glossary_terms,
            last_raw,
            context_before=context_before,
            context_after=context_after,
        )

    def _fallback_invalid_single(
        self,
        source: str,
        glossary_terms,
        raw: str,
        context_before=None,
        context_after=None,
    ) -> str:
        raise RuntimeError(
            f"{self.name()} returned an invalid single-line translation after "
            f"{self.validation_retries} validation retries: {raw[:200]}"
        )

    @staticmethod
    def _matching_terms(texts: Sequence[str], glossary_terms=None) -> list[tuple[str, str]]:
        joined = "\n".join(texts)
        matches = [
            (source, target)
            for source, target in (glossary_terms or [])
            if source in joined
        ]
        return sorted(matches, key=lambda item: len(item[0]), reverse=True)

    def translate(self, text, context_before=None, context_after=None):
        return self.translate_batch(
            [text],
            context_before=context_before,
            context_after=context_after,
        )[0]


# ============ Sakura ============

class SakuraAdapter(OllamaAdapter):
    def __init__(self, config: dict):
        super().__init__(config, "sakura")
        sakura_config = config.get("sakura", {})
        fallback_name = sakura_config.get(
            "validation_fallback_backend", "galtransl"
        )
        fallback_config = config.get(fallback_name, {})
        self.fallback_adapter = None
        if fallback_name == "galtransl" and fallback_config.get("model"):
            self.fallback_adapter = GalTranslAdapter(config)
        self.rescue_models = tuple(sakura_config.get("validation_rescue_models", []))
        self.rescue_base_url = str(
            sakura_config.get("validation_rescue_base_url", "")
        ).rstrip("/")
        self.rescue_api_key_file = str(
            sakura_config.get("validation_rescue_api_key_file", "")
        )
        self.rescue_attempts = max(
            1, int(sakura_config.get("validation_rescue_attempts", 2))
        )
        self.quarantine_on_failure = bool(
            sakura_config.get("validation_quarantine_on_failure", True)
        )

    def _rescue_invalid_single(
        self,
        source: str,
        glossary_terms,
        context_before=None,
        context_after=None,
    ) -> str | None:
        """Use the rotating SenseNova accounts only after both local models fail."""
        if not self.rescue_models or not self.rescue_base_url:
            return None
        # Import lazily so local-only translation has no review-provider dependency.
        from scripts.review_agents import model_chat

        messages = [
            {
                "role": "system",
                "content": (
                    self._system_prompt(self.series_info)
                    + self._context_block(context_before, context_after)
                    + "\n本地翻译模型未通过校验。只输出一行简洁准确的简体中文译文；"
                    "禁止解释、引号包裹、重复或输出日文。"
                ),
            },
            {
                "role": "user",
                "content": self._user_prompt([source], glossary_terms),
            },
        ]
        for model in self.rescue_models:
            for attempt in range(1, self.rescue_attempts + 1):
                try:
                    raw = model_chat(
                        messages,
                        provider="openai",
                        base_url=self.rescue_base_url,
                        api_key_file=self.rescue_api_key_file,
                        model=model,
                        json_mode=False,
                        temperature=0.1,
                        timeout_s=self.timeout_s,
                    )
                except Exception as error:
                    print(
                        f"  Translation rescue {model} failed "
                        f"({attempt}/{self.rescue_attempts}): {error}"
                    )
                    continue
                parsed = self._parse_lines(raw, 1)
                if parsed and self._valid_translation(source, parsed[0]):
                    self._translation_models[source] = model
                    self._translation_fallbacks[source] = True
                    self._translation_errors.pop(source, None)
                    print(f"  Translation validation rescue: {self.model} -> {model}")
                    return parsed[0]
                print(
                    f"  Translation rescue {model} returned invalid output "
                    f"({attempt}/{self.rescue_attempts})"
                )
        return None

    def _quarantine_invalid_single(self, source: str, reason: str) -> str:
        """Preserve a failed line for downstream AI review without poisoning TM."""
        if not self.quarantine_on_failure:
            raise RuntimeError(reason)
        self._translation_models[source] = "untranslated-source-quarantine"
        self._translation_fallbacks[source] = True
        self._translation_errors[source] = reason[:1000]
        print(
            "  WARNING: translation quarantined for multi-agent/MQM review: "
            f"{source[:80]}"
        )
        return source

    def _fallback_invalid_single(
        self,
        source: str,
        glossary_terms,
        raw: str,
        context_before=None,
        context_after=None,
    ) -> str:
        fallback_error = "configured GalTransl fallback is unavailable"
        if self.fallback_adapter is not None:
            self.fallback_adapter.series_info = self.series_info
            try:
                target = _call_batch_with_optional_context(
                    self.fallback_adapter,
                    [source],
                    glossary_terms,
                    context_before=context_before,
                    context_after=context_after,
                )[0]
            except Exception as error:
                fallback_error = str(error)
            else:
                self._translation_models[source] = self.fallback_adapter.result_model(source)
                self._translation_fallbacks[source] = True
                self._translation_errors.pop(source, None)
                print(
                    f"  Translation validation fallback: {self.model} -> "
                    f"{self._translation_models[source]}"
                )
                return target

        rescued = self._rescue_invalid_single(
            source,
            glossary_terms,
            context_before=context_before,
            context_after=context_after,
        )
        if rescued is not None:
            return rescued
        reason = (
            "Sakura validation retries, configured GalTransl fallback, and "
            f"SenseNova rescue all failed; GalTransl error: {fallback_error}; "
            f"last Sakura output: {raw[:200]}"
        )
        return self._quarantine_invalid_single(source, reason)

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
                {
                    "role": "system",
                    "content": self._external_system_prompt()
                    + OllamaAdapter._context_block(context_before, context_after),
                },
                {
                    "role": "user",
                    "content": OllamaAdapter._user_prompt(
                        [text],
                    ),
                },
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

    def _external_system_prompt(self) -> str:
        prompt = "你是一个轻小说翻译模型，可以将日语翻译成简体中文。"
        if self.series_info:
            prompt += f"\n\n系列设定与角色信息：\n{self.series_info}"
        return prompt


def _ensure_builtin_translator_plugins() -> None:
    for name, adapter_class in {
        "sakura": SakuraAdapter,
        "qwen": QwenAdapter,
        "galtransl": GalTranslAdapter,
        "external": ExternalAdapter,
    }.items():
        plugin_registry.register_if_missing(
            "translator",
            name,
            adapter_class,
            source="builtin:translator_adapter",
            description=f"Built-in {adapter_class.__name__}",
        )


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
    parser.add_argument("--backend", type=str, help="Translation backend or plugin name")
    parser.add_argument("--config", type=str, default="", help="Config file path")
    parser.add_argument("--plugin", action="append", default=[],
                        help="Trusted local plugin .py file (repeatable)")
    parser.add_argument("--list-backends", action="store_true", help="List available backends")
    parser.add_argument("--save-config", type=str, help="Save default config to file")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    load_plugins(args.plugin)
    _ensure_builtin_translator_plugins()

    if args.list_backends:
        print("Available backends:")
        for spec in plugin_registry.specs("translator"):
            print(f"  {spec['name']:<12} {spec['description']} [{spec['source']}]")
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
