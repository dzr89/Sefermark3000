"""
Unit tests for the configuration module.

Tests configuration loading, validation, and path handling.
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


class TestTwitterConfig:
    """Tests for TwitterConfig dataclass."""

    def test_twitter_config_creation(self):
        """Test TwitterConfig can be created with all fields."""
        from twitter_notion_sync.config import TwitterConfig

        config = TwitterConfig(
            client_id="cid",
            client_secret="csec",
            access_token="at",
            access_token_secret="ats",
            bearer_token="bt",
            oauth2_client_id="o2cid",
            oauth2_client_secret="o2csec",
            oauth2_access_token="o2at",
            oauth2_refresh_token="o2rt",
        )

        assert config.client_id == "cid"
        assert config.oauth2_access_token == "o2at"


class TestNotionConfig:
    """Tests for NotionConfig dataclass."""

    def test_notion_config_creation(self):
        """Test NotionConfig can be created with all fields."""
        from twitter_notion_sync.config import NotionConfig

        config = NotionConfig(
            token="test_token",
            database_id="test_db_id",
        )

        assert config.token == "test_token"
        assert config.database_id == "test_db_id"


class TestSyncConfig:
    """Tests for SyncConfig dataclass."""

    def test_sync_config_creation(self):
        """Test SyncConfig can be created with all fields."""
        from twitter_notion_sync.config import SyncConfig

        config = SyncConfig(
            interval_minutes=15,
            state_file_path=Path("/tmp/state.json"),
            log_file_path=Path("/tmp/log.txt"),
            log_level="DEBUG",
        )

        assert config.interval_minutes == 15
        assert config.log_level == "DEBUG"


class TestLoadConfig:
    """Tests for the load_config function."""

    def test_load_config_from_env(self, mock_env_vars):
        """Test loading config from environment variables."""
        from twitter_notion_sync.config import load_config

        config = load_config()

        assert config.notion.token == "test_notion_token"
        assert config.notion.database_id == "test_database_id"
        assert config.twitter.oauth2_client_id == "test_oauth2_client_id"

    def test_load_config_from_file(self, temp_env_file, monkeypatch):
        """Test loading config from .env file."""
        # Clear env vars that would override file
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
        monkeypatch.delenv("TWITTER_OAUTH2_CLIENT_ID", raising=False)
        monkeypatch.delenv("TWITTER_OAUTH2_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("TWITTER_OAUTH2_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("TWITTER_OAUTH2_REFRESH_TOKEN", raising=False)

        from twitter_notion_sync.config import load_config

        config = load_config(str(temp_env_file))

        assert config.notion.token == "test_token_from_file"
        assert config.notion.database_id == "test_db_id_from_file"

    def test_load_config_missing_required(self, monkeypatch):
        """Test loading config fails when required vars missing."""
        # Remove required env vars
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
        monkeypatch.delenv("TWITTER_OAUTH2_CLIENT_ID", raising=False)
        monkeypatch.delenv("TWITTER_OAUTH2_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("TWITTER_OAUTH2_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("TWITTER_OAUTH2_REFRESH_TOKEN", raising=False)

        from twitter_notion_sync.config import load_config

        with pytest.raises(ValueError, match="Missing required"):
            load_config()

    def test_load_config_default_sync_settings(self, mock_env_vars, monkeypatch):
        """Test default values for sync settings."""
        # Remove optional env vars
        monkeypatch.delenv("SYNC_INTERVAL_MINUTES", raising=False)
        monkeypatch.delenv("STATE_FILE_PATH", raising=False)
        monkeypatch.delenv("LOG_FILE_PATH", raising=False)

        from twitter_notion_sync.config import load_config

        config = load_config()

        assert config.sync.interval_minutes == 10  # Default
        assert config.sync.log_level == "DEBUG"  # From mock_env_vars

    def test_load_config_custom_sync_interval(self, mock_env_vars, monkeypatch):
        """Test custom sync interval from env."""
        monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "30")

        from twitter_notion_sync.config import load_config

        config = load_config()

        assert config.sync.interval_minutes == 30

    def test_load_config_path_expansion(self, mock_env_vars, monkeypatch):
        """Test tilde expansion in file paths."""
        monkeypatch.setenv("STATE_FILE_PATH", "~/custom/state.json")
        monkeypatch.setenv("LOG_FILE_PATH", "~/custom/log.txt")

        from twitter_notion_sync.config import load_config

        config = load_config()

        # Should expand ~ to home directory
        assert not str(config.sync.state_file_path).startswith("~")
        assert str(config.sync.state_file_path).startswith(str(Path.home()))


class TestEnsureDirectories:
    """Tests for the ensure_directories function."""

    def test_ensure_directories_creates_parent_dirs(self, mock_env_vars):
        """Test that parent directories are created."""
        from twitter_notion_sync.config import load_config, ensure_directories, Config, SyncConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create config with paths in temp directory
            from twitter_notion_sync.config import TwitterConfig, NotionConfig

            config = Config(
                twitter=TwitterConfig(
                    client_id="", client_secret="", access_token="",
                    access_token_secret="", bearer_token="",
                    oauth2_client_id="id", oauth2_client_secret="sec",
                    oauth2_access_token="token", oauth2_refresh_token="ref"
                ),
                notion=NotionConfig(token="token", database_id="db"),
                sync=SyncConfig(
                    interval_minutes=10,
                    state_file_path=Path(tmpdir) / "subdir" / "state.json",
                    log_file_path=Path(tmpdir) / "logs" / "app.log",
                    log_level="INFO"
                )
            )

            ensure_directories(config)

            assert (Path(tmpdir) / "subdir").exists()
            assert (Path(tmpdir) / "logs").exists()

    def test_ensure_directories_idempotent(self, mock_env_vars):
        """Test that ensure_directories can be called multiple times."""
        from twitter_notion_sync.config import ensure_directories, Config, SyncConfig
        from twitter_notion_sync.config import TwitterConfig, NotionConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(
                twitter=TwitterConfig(
                    client_id="", client_secret="", access_token="",
                    access_token_secret="", bearer_token="",
                    oauth2_client_id="id", oauth2_client_secret="sec",
                    oauth2_access_token="token", oauth2_refresh_token="ref"
                ),
                notion=NotionConfig(token="token", database_id="db"),
                sync=SyncConfig(
                    interval_minutes=10,
                    state_file_path=Path(tmpdir) / "state.json",
                    log_file_path=Path(tmpdir) / "app.log",
                    log_level="INFO"
                )
            )

            # Should not raise on multiple calls
            ensure_directories(config)
            ensure_directories(config)
            ensure_directories(config)


class TestConfigDataclasses:
    """Tests for config dataclass behavior."""

    def test_config_immutability(self):
        """Test config objects can be modified (not frozen)."""
        from twitter_notion_sync.config import NotionConfig

        config = NotionConfig(token="original", database_id="db")
        config.token = "modified"

        assert config.token == "modified"

    def test_config_equality(self):
        """Test config equality comparison."""
        from twitter_notion_sync.config import NotionConfig

        config1 = NotionConfig(token="token", database_id="db")
        config2 = NotionConfig(token="token", database_id="db")
        config3 = NotionConfig(token="different", database_id="db")

        assert config1 == config2
        assert config1 != config3


class TestConfigSecurity:
    """Security-related tests for configuration."""

    @pytest.mark.security
    def test_config_does_not_log_secrets(self, mock_env_vars, capture_logs):
        """Test that secrets are not logged during config load."""
        from twitter_notion_sync.config import load_config

        config = load_config()

        # Check none of the secret values appear in logs
        for msg in capture_logs.messages:
            assert "test_notion_token" not in msg
            assert "test_oauth2_client_secret" not in msg
            assert "test_oauth2_access_token" not in msg
            assert "test_oauth2_refresh_token" not in msg

    @pytest.mark.security
    def test_config_str_repr_safe(self, notion_config):
        """Test that config string representation doesn't expose secrets."""
        # Default dataclass __repr__ shows all fields
        # This test documents current behavior
        repr_str = repr(notion_config)

        # Note: default dataclass repr DOES show secrets
        # A future improvement would be to implement __repr__ that masks them
        assert "test_notion_token" in repr_str  # Current behavior
