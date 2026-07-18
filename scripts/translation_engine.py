"""Resumable, glossary-aware batch translation for subtitle segments."""

from __future__ import annotations

import json
import inspect
from pathlib import Path
from typing import Sequence

from scripts.glossary import Glossary
from scripts.translation_memory import TranslationMemory
from scripts.translator_adapter import TranslatorAdapter


def _atomic_write_json(path: Path, data: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(list(data), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


class PipelineTranslator:
    """Translate ASR segments in validated batches with persistent resume state."""

    def __init__(
        self,
        adapter: TranslatorAdapter,
        glossary: Glossary | None = None,
        memory: TranslationMemory | None = None,
        batch_size: int | None = None,
        context_window: int = 0,
    ):
        self.adapter = adapter
        self.glossary = glossary
        self.memory = memory
        configured_batch_size = getattr(adapter, "batch_size", 16)
        self.batch_size = max(1, int(batch_size or configured_batch_size))
        self.context_window = max(0, int(context_window))

    def translate(
        self,
        segments: Sequence[dict],
        progress_path: str | Path | None = None,
    ) -> list[dict]:
        output: list[dict | None] = [None] * len(segments)
        progress = Path(progress_path) if progress_path else None
        for start in range(0, len(segments), self.batch_size):
            stop = min(len(segments), start + self.batch_size)
            batch = segments[start:stop]
            missing_indices = []
            missing_sources = []
            missing_contexts = []

            for offset, segment in enumerate(batch):
                index = start + offset
                source = str(segment.get("text", "")).strip()
                context_before, context_after = self._context_for(segments, index)
                cached = (
                    self.memory.lookup_entry(source, context_before, context_after)
                    if self.memory
                    else None
                )
                if cached and cached.get("zh"):
                    output[index] = self._result(
                        segment,
                        source,
                        cached["zh"],
                        cached=True,
                        model=cached.get("model"),
                        fallback=bool(cached.get("translation_fallback", False)),
                    )
                else:
                    missing_indices.append(index)
                    missing_sources.append(source)
                    missing_contexts.append((context_before, context_after))

            if missing_sources:
                if self.context_window:
                    translated = []
                    for source, (context_before, context_after) in zip(
                        missing_sources,
                        missing_contexts,
                    ):
                        translated.extend(
                            self._translate_batch(
                                [source],
                                self._matching_glossary_terms([source]),
                                context_before,
                                context_after,
                            )
                        )
                else:
                    translated = self._translate_batch(
                        missing_sources,
                        self._matching_glossary_terms(missing_sources),
                        None,
                        None,
                    )
                if len(translated) != len(missing_sources):
                    raise RuntimeError(
                        "Translation backend returned a different number of lines: "
                        f"{len(translated)} != {len(missing_sources)}"
                    )
                for index, source, target, contexts in zip(
                    missing_indices,
                    missing_sources,
                    translated,
                    missing_contexts,
                ):
                    segment = segments[index]
                    model = self._result_model(source)
                    fallback = self._result_is_fallback(source)
                    output[index] = self._result(
                        segment,
                        source,
                        target,
                        cached=False,
                        model=model,
                        fallback=fallback,
                    )
                    if self.memory:
                        self.memory.store(
                            source,
                            target,
                            model=model,
                            fallback=fallback,
                            context_before=contexts[0],
                            context_after=contexts[1],
                        )

            if self.memory:
                self.memory.save()
            if progress:
                completed = [item for item in output if item is not None]
                _atomic_write_json(progress, completed)
            print(f"  Translated: {stop}/{len(segments)}")

        if any(item is None for item in output):
            raise RuntimeError("Translation finished with missing subtitle segments")
        return [item for item in output if item is not None]

    def _context_for(
        self,
        segments: Sequence[dict],
        index: int,
    ) -> tuple[list[str] | None, list[str] | None]:
        if not self.context_window:
            return None, None
        context_before = [
            str(item.get("text", "")).strip()
            for item in segments[max(0, index - self.context_window):index]
            if str(item.get("text", "")).strip()
        ]
        context_after = [
            str(item.get("text", "")).strip()
            for item in segments[
                index + 1:min(len(segments), index + 1 + self.context_window)
            ]
            if str(item.get("text", "")).strip()
        ]
        return context_before, context_after

    def _translate_batch(
        self,
        sources: Sequence[str],
        glossary_terms: Sequence[tuple[str, str]],
        context_before: Sequence[str] | None,
        context_after: Sequence[str] | None,
    ) -> list[str]:
        """Pass context to capable adapters without breaking older plugins."""
        method = self.adapter.translate_batch
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
                sources,
                glossary_terms,
                context_before=context_before,
                context_after=context_after,
            )
        return method(sources, glossary_terms)

    def _matching_glossary_terms(self, sources: Sequence[str]) -> list[tuple[str, str]]:
        if not self.glossary:
            return []
        joined = "\n".join(sources)
        # Sending a large unrelated dictionary can make Sakura repeat or emit
        # garbage. Only include terms that occur in this translation batch.
        matches = [
            (source, target)
            for source, target in self.glossary.terms
            if source in joined
        ]
        return sorted(matches, key=lambda item: len(item[0]), reverse=True)

    def _result_model(self, source: str) -> str:
        if hasattr(self.adapter, "result_model"):
            return self.adapter.result_model(source)
        return getattr(self.adapter, "model", self.adapter.name())

    def _result_is_fallback(self, source: str) -> bool:
        if hasattr(self.adapter, "result_is_fallback"):
            return bool(self.adapter.result_is_fallback(source))
        return False

    def _result(
        self,
        segment: dict,
        source: str,
        target: str,
        cached: bool,
        model: str | None = None,
        fallback: bool = False,
    ) -> dict:
        model = model or self._result_model(source)
        result = {
            "start": segment["start"],
            "end": segment["end"],
            "ja": source,
            "text": target.strip(),
            "translation_model": model,
            "translation_cached": cached,
            "translation_fallback": fallback,
        }
        if "confidence" in segment:
            result["asr_confidence"] = segment["confidence"]
        if segment.get("speaker"):
            result["speaker"] = segment["speaker"]
        for key in ("source", "subtitle_index"):
            if key in segment:
                result[key] = segment[key]
        return result
