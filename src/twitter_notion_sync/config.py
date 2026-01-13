"""
Configuration management for Twitter-Notion Sync.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv


@dataclass
class TwitterConfig:
    """Twitter API configuration."""
    client_id: str
    client_secret: str
    access_token: str
    access_token_secret: str
    bearer_token: str
    # OAuth 2.0 User Context (required for bookmarks)
    oauth2_client_id: str
    oauth2_client_secret: str
    oauth2_access_token: str
    oauth2_refresh_token: str


@dataclass
class NotionConfig:
    """Notion API configuration."""
    token: str
    database_id: str


@dataclass
class SyncConfig:
    """Sync service configuration."""
    interval_minutes: int
    state_file_path: Path
    log_file_path: Path
    log_level: str


@dataclass
class Config:
    """Main configuration container."""
    twitter: TwitterConfig
    notion: NotionConfig
    sync: SyncConfig


def load_config(env_path: Optional[str] = None) -> Config:
    """
    Load configuration from environment variables.

    Args:
        env_path: Optional path to .env file

    Returns:
        Config object with all settings

    Raises:
        ValueError: If required configuration is missing
    """
    # Load .env file if it exists
    if env_path:
        load_dotenv(env_path)
    else:
        # Try to find .env in common locations
        for path in [".env", Path.home() / ".twitter_notion_sync" / ".env"]:
            if Path(path).exists():
                load_dotenv(path)
                break

    # Helper to get required env var
    def get_required(key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Missing required environment variable: {key}")
        return value

    # Helper to expand path
    def expand_path(path_str: str) -> Path:
        return Path(os.path.expanduser(path_str))

    # Load Twitter config
    twitter = TwitterConfig(
        client_id=os.getenv("TWITTER_CLIENT_ID", ""),
        client_secret=os.getenv("TWITTER_CLIENT_SECRET", ""),
        access_token=os.getenv("TWITTER_ACCESS_TOKEN", ""),
        access_token_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET", ""),
        bearer_token=os.getenv("TWITTER_BEARER_TOKEN", ""),
        oauth2_client_id=get_required("TWITTER_OAUTH2_CLIENT_ID"),
        oauth2_client_secret=get_required("TWITTER_OAUTH2_CLIENT_SECRET"),
        oauth2_access_token=get_required("TWITTER_OAUTH2_ACCESS_TOKEN"),
        oauth2_refresh_token=get_required("TWITTER_OAUTH2_REFRESH_TOKEN"),
    )

    # Load Notion config
    notion = NotionConfig(
        token=get_required("NOTION_TOKEN"),
        database_id=get_required("NOTION_DATABASE_ID"),
    )

    # Load sync config with defaults
    default_state_path = "~/.twitter_notion_sync/state.json"
    default_log_path = "~/.twitter_notion_sync/sync.log"

    sync = SyncConfig(
        interval_minutes=int(os.getenv("SYNC_INTERVAL_MINUTES", "10")),
        state_file_path=expand_path(os.getenv("STATE_FILE_PATH", default_state_path)),
        log_file_path=expand_path(os.getenv("LOG_FILE_PATH", default_log_path)),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )

    return Config(twitter=twitter, notion=notion, sync=sync)


def ensure_directories(config: Config) -> None:
    """Ensure required directories exist."""
    config.sync.state_file_path.parent.mkdir(parents=True, exist_ok=True)
    config.sync.log_file_path.parent.mkdir(parents=True, exist_ok=True)
