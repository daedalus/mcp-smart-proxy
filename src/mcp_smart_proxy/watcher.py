from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import structlog
import yaml
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from mcp_smart_proxy.config import TransportType, UpstreamConfig

logger = structlog.get_logger(__name__)


class UpstreamFileHandler(FileSystemEventHandler):
    def __init__(
        self,
        watch_dir: Path,
        on_upstream_added: Callable[[UpstreamConfig], None],
        on_upstream_removed: Callable[[str], None],
    ):
        self._watch_dir = watch_dir
        self._on_upstream_added = on_upstream_added
        self._on_upstream_removed = on_upstream_removed
        self._loaded_files: dict[Path, str] = {}

    def _is_config_file(self, path: Path) -> bool:
        return path.suffix.lower() in {".yaml", ".yml", ".json"}

    def _load_upstream_config(self, path: Path) -> UpstreamConfig | None:
        try:
            with open(path) as f:
                if path.suffix.lower() == ".json":
                    data = json.load(f)
                else:
                    data = yaml.safe_load(f)
            if not isinstance(data, dict):
                return None
            if "id" not in data:
                logger.warning("config_file_missing_id", path=str(path))
                return None
            if "transport" not in data:
                logger.warning("config_file_missing_transport", path=str(path))
                return None
            data["transport"] = TransportType(data["transport"])
            return UpstreamConfig(**data)
        except Exception as e:
            logger.error("failed_to_load_config", path=str(path), error=str(e))
            return None

    def _get_file_key(self, path: Path) -> str:
        return str(path.absolute())

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not self._is_config_file(path):
            return
        logger.info("watcher_file_created", path=str(path))
        self._handle_file(path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not self._is_config_file(path):
            return
        logger.info("watcher_file_modified", path=str(path))
        self._handle_file(path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if not self._is_config_file(path):
            return
        key = self._get_file_key(path)
        if key in self._loaded_files:
            server_id = self._loaded_files.pop(key)
            self._on_upstream_removed(server_id)
            logger.info("watcher_file_deleted", path=str(path), server_id=server_id)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        old_path = Path(event.src_path)
        new_path = Path(event.dest_path)
        if not self._is_config_file(old_path) and not self._is_config_file(new_path):
            return
        key = self._get_file_key(old_path)
        if key in self._loaded_files:
            server_id = self._loaded_files.pop(key)
            self._on_upstream_removed(server_id)
        self._handle_file(new_path)

    def _handle_file(self, path: Path) -> None:
        key = self._get_file_key(path)
        config = self._load_upstream_config(path)
        if config is None:
            return
        self._on_upstream_added(config)
        self._loaded_files[key] = config.id
        logger.info("watcher_upstream_loaded", path=str(path), server_id=config.id)

    def load_existing(self) -> None:
        for path in self._watch_dir.iterdir():
            if path.is_file() and self._is_config_file(path):
                self._handle_file(path)


class UpstreamWatcher:
    def __init__(
        self,
        watch_dir: Path,
        on_upstream_added: Callable[[UpstreamConfig], None],
        on_upstream_removed: Callable[[str], None],
    ):
        self._watch_dir = watch_dir
        self._on_upstream_added = on_upstream_added
        self._on_upstream_removed = on_upstream_removed
        self._observer: Observer | None = None
        self._handler: UpstreamFileHandler | None = None

    def start(self) -> None:
        if not self._watch_dir.exists():
            raise FileNotFoundError(
                f"Watch directory does not exist: {self._watch_dir}"
            )
        if not self._watch_dir.is_dir():
            raise NotADirectoryError(
                f"Watch path is not a directory: {self._watch_dir}"
            )

        self._handler = UpstreamFileHandler(
            self._watch_dir,
            self._on_upstream_added,
            self._on_upstream_removed,
        )
        self._observer = Observer()
        self._observer.schedule(self._handler, str(self._watch_dir), recursive=False)
        self._observer.start()
        self._handler.load_existing()
        logger.info("watcher_started", watch_dir=str(self._watch_dir))

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("watcher_stopped")

    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
