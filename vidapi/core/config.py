"""Configuration management for vidapi.

Handles persistent settings stored in a JSON file in the user's config directory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from vidapi.core.system_utils import get_platform_config_dir

logger = logging.getLogger(__name__)


class Config:
    """Manages application configuration with persistence to JSON file."""

    DEFAULT_CONFIG = {
        "version": 1,
        "download_mode": "完整视频（画面+声音）",
        "quality": "最佳",
        "download_dir": "",  # Empty = use default Downloads folder
        "proxy": "",  # Empty = auto-detect
        "concurrency": 3,
        "auto_merge": True,
        "cookie_header": "",  # Raw Cookie: header string for BiliBili
    }

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is None:
            config_dir = get_platform_config_dir("vidapi")
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "config.json"

        self.config_path = config_path
        self._data = self.DEFAULT_CONFIG.copy()
        self.load()

    def load(self) -> None:
        """Load configuration from JSON file."""
        try:
            if self.config_path.exists():
                with self.config_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge with defaults to handle version upgrades
                self._data = {**self.DEFAULT_CONFIG, **loaded}
                logger.debug("Loaded config from %s", self.config_path)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load config: %s, using defaults", e)
            self._data = self.DEFAULT_CONFIG.copy()

    def save(self) -> None:
        """Save configuration to JSON file."""
        try:
            with self.config_path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            logger.debug("Saved config to %s", self.config_path)
        except OSError as e:
            logger.error("Failed to save config: %s", e)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value and save."""
        self._data[key] = value
        self.save()

    def update(self, values: dict[str, Any]) -> None:
        """Update multiple configuration values and save."""
        self._data.update(values)
        self.save()

    @property
    def download_mode(self) -> str:
        return str(self._data.get("download_mode", self.DEFAULT_CONFIG["download_mode"]))

    @download_mode.setter
    def download_mode(self, value: str) -> None:
        self.set("download_mode", value)

    @property
    def quality(self) -> str:
        return str(self._data.get("quality", self.DEFAULT_CONFIG["quality"]))

    @quality.setter
    def quality(self, value: str) -> None:
        self.set("quality", value)

    @property
    def download_dir(self) -> str:
        return str(self._data.get("download_dir", ""))

    @download_dir.setter
    def download_dir(self, value: str) -> None:
        self.set("download_dir", value)

    @property
    def proxy(self) -> str:
        return str(self._data.get("proxy", ""))

    @proxy.setter
    def proxy(self, value: str) -> None:
        self.set("proxy", value)

    @property
    def concurrency(self) -> int:
        return int(self._data.get("concurrency", self.DEFAULT_CONFIG["concurrency"]))

    @concurrency.setter
    def concurrency(self, value: int) -> None:
        self.set("concurrency", value)

    @property
    def auto_merge(self) -> bool:
        return bool(self._data.get("auto_merge", self.DEFAULT_CONFIG["auto_merge"]))

    @auto_merge.setter
    def auto_merge(self, value: bool) -> None:
        self.set("auto_merge", value)

    @property
    def cookie_header(self) -> str:
        return str(self._data.get("cookie_header", self.DEFAULT_CONFIG["cookie_header"]))

    @cookie_header.setter
    def cookie_header(self, value: str) -> None:
        self.set("cookie_header", value)


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config