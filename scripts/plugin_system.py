"""Plugin registry for translation, ASR, and subtitle style extensions."""

import argparse
import importlib.metadata
import importlib.util
import json
import re
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


PLUGIN_KINDS = {"translator", "asr", "subtitle_style"}
ENTRY_POINT_GROUP = "anime_accurate_sub.plugins"
PLUGIN_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


@dataclass(frozen=True)
class PluginSpec:
    kind: str
    name: str
    factory: Callable[[dict[str, Any]], Any]
    source: str
    description: str = ""

    def public_dict(self) -> dict[str, str]:
        data = asdict(self)
        data.pop("factory")
        return data


class PluginRegistry:
    """Thread-safe plugin registry with explicit contracts and source tracking."""

    def __init__(self):
        self._plugins: dict[str, dict[str, PluginSpec]] = {
            kind: {} for kind in sorted(PLUGIN_KINDS)
        }
        self._loaded_sources: set[str] = set()
        self._lock = threading.RLock()

    def register(
        self,
        kind: str,
        name: str,
        factory: Callable[[dict[str, Any]], Any],
        *,
        source: str = "external",
        description: str = "",
        replace: bool = False,
    ) -> PluginSpec:
        kind = str(kind).strip().lower()
        name = str(name).strip().lower()
        if kind not in PLUGIN_KINDS:
            raise ValueError(f"未知插件类型：{kind}；可用类型：{sorted(PLUGIN_KINDS)}")
        if not PLUGIN_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                "插件名必须以小写字母开头，只能包含小写字母、数字、点、短横线和下划线"
            )
        if not callable(factory):
            raise TypeError("插件 factory 必须可调用")
        with self._lock:
            if name in self._plugins[kind] and not replace:
                previous = self._plugins[kind][name]
                raise ValueError(
                    f"插件已注册：{kind}/{name}（来源：{previous.source}）"
                )
            spec = PluginSpec(kind, name, factory, str(source), str(description))
            self._plugins[kind][name] = spec
            return spec

    def register_if_missing(
        self,
        kind: str,
        name: str,
        factory: Callable[[dict[str, Any]], Any],
        **kwargs,
    ) -> PluginSpec:
        normalized_kind, normalized_name = str(kind).lower(), str(name).lower()
        with self._lock:
            existing = self._plugins.get(normalized_kind, {}).get(normalized_name)
            if existing:
                return existing
            return self.register(kind, name, factory, **kwargs)

    def unregister(self, kind: str, name: str) -> None:
        with self._lock:
            self._plugins.get(kind, {}).pop(name, None)

    def has(self, kind: str, name: str) -> bool:
        return str(name).lower() in self._plugins.get(str(kind).lower(), {})

    def names(self, kind: str) -> list[str]:
        if kind not in PLUGIN_KINDS:
            raise ValueError(f"未知插件类型：{kind}")
        return sorted(self._plugins[kind])

    def specs(self, kind: str | None = None) -> list[dict[str, str]]:
        kinds = [kind] if kind else sorted(PLUGIN_KINDS)
        result = []
        for current in kinds:
            if current not in PLUGIN_KINDS:
                raise ValueError(f"未知插件类型：{current}")
            result.extend(
                self._plugins[current][name].public_dict()
                for name in sorted(self._plugins[current])
            )
        return result

    def create(self, kind: str, name: str, config: dict[str, Any] | None = None) -> Any:
        kind, name = str(kind).lower(), str(name).lower()
        with self._lock:
            spec = self._plugins.get(kind, {}).get(name)
        if spec is None:
            available = self.names(kind) if kind in PLUGIN_KINDS else []
            raise ValueError(f"未知 {kind} 插件：{name}；可用：{available}")
        instance = spec.factory(dict(config or {}))
        self._validate_instance(kind, name, instance)
        return instance

    @staticmethod
    def _validate_instance(kind: str, name: str, instance: Any) -> None:
        if kind == "translator":
            missing = [
                attr
                for attr in ("translate", "translate_batch", "name")
                if not callable(getattr(instance, attr, None))
            ]
            if missing:
                raise TypeError(f"translator 插件 {name} 缺少方法：{missing}")
        elif kind == "asr" and not callable(getattr(instance, "transcribe", None)):
            raise TypeError(f"asr 插件 {name} 缺少 transcribe 方法")
        elif kind == "subtitle_style" and not isinstance(instance, dict):
            raise TypeError(f"subtitle_style 插件 {name} 必须返回样式字典")

    def _register_from_target(self, target: Any, source: str) -> None:
        callback = getattr(target, "register_plugins", None) or getattr(target, "register", None)
        if callback is None and callable(target):
            callback = target
        if not callable(callback):
            raise TypeError(
                f"插件入口 {source} 必须是注册函数，或提供 register_plugins(registry)"
            )
        callback(self)

    def load_file(self, path: str | Path) -> str:
        """Execute a trusted local Python plugin and let it register factories."""
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file() or resolved.suffix.lower() != ".py":
            raise FileNotFoundError(f"插件文件不存在或不是 .py：{resolved}")
        source = f"file:{resolved}"
        with self._lock:
            if source in self._loaded_sources:
                return source
        module_name = f"anime_accurate_sub_plugin_{abs(hash(str(resolved))):x}"
        spec = importlib.util.spec_from_file_location(module_name, resolved)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载插件：{resolved}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            self._register_from_target(module, source)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        with self._lock:
            self._loaded_sources.add(source)
        return source

    def discover_entry_points(
        self,
        group: str = ENTRY_POINT_GROUP,
        strict: bool = False,
    ) -> list[dict[str, str]]:
        """Discover installed plugin registration callbacks through package metadata."""
        discovered = []
        entry_points = importlib.metadata.entry_points()
        selected = entry_points.select(group=group) if hasattr(entry_points, "select") else entry_points.get(group, [])
        for entry in selected:
            source = f"entry-point:{entry.name}={entry.value}"
            with self._lock:
                if source in self._loaded_sources:
                    continue
            try:
                self._register_from_target(entry.load(), source)
                with self._lock:
                    self._loaded_sources.add(source)
                discovered.append({"source": source, "status": "loaded"})
            except Exception as error:
                discovered.append({"source": source, "status": "error", "error": str(error)})
                if strict:
                    raise
        return discovered


plugin_registry = PluginRegistry()


def load_plugins(paths: list[str] | None = None, discover: bool = True) -> dict[str, Any]:
    loaded_files = [plugin_registry.load_file(path) for path in (paths or [])]
    entry_points = plugin_registry.discover_entry_points() if discover else []
    return {"files": loaded_files, "entry_points": entry_points}


def main() -> None:
    parser = argparse.ArgumentParser(description="Anime Accurate Sub plugin registry")
    parser.add_argument("--plugin", action="append", default=[], help="Trusted local .py plugin")
    parser.add_argument("--no-entry-points", action="store_true")
    parser.add_argument("--kind", choices=sorted(PLUGIN_KINDS))
    args = parser.parse_args()
    result = load_plugins(args.plugin, discover=not args.no_entry_points)
    print(json.dumps({"loaded": result, "plugins": plugin_registry.specs(args.kind)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
