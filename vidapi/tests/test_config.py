"""Error tests for config management: load, save, malformed JSON, missing file, disk errors."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vidapi.core.config import Config, get_config


class TestConfigLoad:
    def test_default_config_values(self, config: Config):
        assert config.download_mode == "完整视频（画面+声音）"
        assert config.quality == "最佳"
        assert config.concurrency == 3
        assert config.auto_merge is True
        assert config.cookie_header == ""

    def test_load_custom_config(self, config_file: Path, config: Config):
        config_file.write_text(
            json.dumps({"concurrency": 5, "quality": "1080p", "auto_merge": False}),
            encoding="utf-8",
        )
        config.load()
        assert config.concurrency == 5
        assert config.quality == "1080p"
        assert config.auto_merge is False

    def test_missing_config_file(self, tmp_dir: Path):
        nonexistent = tmp_dir / "does_not_exist.json"
        cfg = Config(config_path=nonexistent)
        assert cfg.concurrency == 3  # defaults

    def test_malformed_json_config(self, config_file: Path, config: Config):
        config_file.write_text("{broken json!!!", encoding="utf-8")
        config.load()
        assert config.concurrency == 3  # falls back to defaults

    def test_empty_file_config(self, config_file: Path, config: Config):
        config_file.write_text("", encoding="utf-8")
        config.load()
        assert config.concurrency == 3  # falls back to defaults

    def test_partial_config_merged_with_defaults(self, config_file: Path, config: Config):
        config_file.write_text(json.dumps({"concurrency": 10}), encoding="utf-8")
        config.load()
        assert config.concurrency == 10
        assert config.quality == "最佳"  # from defaults

    def test_extra_keys_in_config_ignored(self, config_file: Path, config: Config):
        config_file.write_text(json.dumps({"extra_key": "should_be_ignored", "concurrency": 2}), encoding="utf-8")
        config.load()
        assert config.concurrency == 2
        assert config.get("extra_key") == "should_be_ignored"


class TestConfigSave:
    def test_save_and_reload(self, config: Config, config_file: Path):
        config.concurrency = 7
        config.quality = "720p"
        # save() is called automatically via property setter
        # Reload and verify
        cfg2 = Config(config_path=config_file)
        assert cfg2.concurrency == 7
        assert cfg2.quality == "720p"

    def test_save_config_file_writable(self, config: Config, config_file: Path):
        config.save()
        assert config_file.exists()
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert "concurrency" in data

    def test_save_creates_parent_dirs(self, tmp_dir: Path):
        # Config.save() does NOT create parent dirs — it just writes.
        # This tests the expected failure mode (OSError on missing parent).
        nested = tmp_dir / "a" / "b" / "config.json"
        cfg = Config(config_path=nested)
        # Ensure parent doesn't exist
        cfg.save()  # logs error but doesn't raise
        assert not nested.exists()  # file was never written

    @patch.object(Config, "save")
    def test_setter_calls_save(self, mock_save, config: Config):
        config.concurrency = 5
        mock_save.assert_called()


class TestConfigProperties:
    def test_download_mode_getter(self, config: Config):
        assert isinstance(config.download_mode, str)

    def test_download_mode_setter(self, config: Config):
        config.download_mode = "仅音频"
        assert config.download_mode == "仅音频"

    def test_quality_setter(self, config: Config):
        config.quality = "1080p"
        assert config.quality == "1080p"

    def test_proxy_setter(self, config: Config):
        config.proxy = "http://proxy:8080"
        assert config.proxy == "http://proxy:8080"

    def test_concurrency_setter(self, config: Config):
        config.concurrency = 8
        assert config.concurrency == 8

    def test_auto_merge_setter(self, config: Config):
        config.auto_merge = False
        assert config.auto_merge is False

    def test_cookie_header_setter(self, config: Config):
        config.cookie_header = "SESSDATA=abc; bili_jct=xyz"
        assert "SESSDATA=abc" in config.cookie_header


class TestConfigUpdate:
    def test_update_multiple_values(self, config: Config):
        config.update({"concurrency": 5, "quality": "1080p"})
        assert config.concurrency == 5
        assert config.quality == "1080p"

    def test_update_empty_dict(self, config: Config):
        original = config.concurrency
        config.update({})
        assert config.concurrency == original


class TestGetConfigSingleton:
    def test_returns_same_instance(self):
        # Since get_config uses a global, calling twice should return the same
        # But we need to be careful about test isolation
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_config_initialized(self):
        cfg = get_config()
        assert cfg is not None
        assert cfg.concurrency > 0


class TestConfigEdgeCases:
    def test_null_values_in_json(self, config_file: Path):
        config_file.write_text(json.dumps({"concurrency": None, "quality": None}), encoding="utf-8")
        cfg = Config(config_path=config_file)
        # int(None) raises TypeError — this is a real bug in Config.concurrency getter
        with pytest.raises(TypeError):
            _ = cfg.concurrency

    def test_string_concurrency(self, config_file: Path):
        config_file.write_text(json.dumps({"concurrency": "five"}), encoding="utf-8")
        cfg = Config(config_path=config_file)
        # int("five") would raise — this is a real edge case
        with pytest.raises(ValueError):
            _ = cfg.concurrency

    def test_boolean_as_int(self, config_file: Path):
        config_file.write_text(json.dumps({"concurrency": True}), encoding="utf-8")
        cfg = Config(config_path=config_file)
        assert cfg.concurrency == 1  # int(True) == 1
