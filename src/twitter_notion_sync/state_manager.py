"""
State management for tracking synced tweets.

Uses a JSON file to persist the IDs of tweets that have been synced to Notion.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Set, Optional
from dataclasses import dataclass, field, asdict
from filelock import FileLock

logger = logging.getLogger(__name__)


@dataclass
class SyncState:
    """Represents the current sync state."""
    synced_tweet_ids: Set[str] = field(default_factory=set)
    last_sync_time: Optional[str] = None
    total_synced_count: int = 0
    last_bookmark_id: Optional[str] = None  # For pagination

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "synced_tweet_ids": list(self.synced_tweet_ids),
            "last_sync_time": self.last_sync_time,
            "total_synced_count": self.total_synced_count,
            "last_bookmark_id": self.last_bookmark_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SyncState":
        """Create from dictionary."""
        return cls(
            synced_tweet_ids=set(data.get("synced_tweet_ids", [])),
            last_sync_time=data.get("last_sync_time"),
            total_synced_count=data.get("total_synced_count", 0),
            last_bookmark_id=data.get("last_bookmark_id"),
        )


class StateManager:
    """
    Manages persistent state for tweet sync tracking.

    Uses file locking to prevent concurrent access issues.
    """

    def __init__(self, state_file_path: Path):
        """
        Initialize the state manager.

        Args:
            state_file_path: Path to the state JSON file
        """
        self.state_file_path = state_file_path
        self.lock_file_path = state_file_path.with_suffix(".lock")
        self._state: Optional[SyncState] = None

    def _ensure_directory_exists(self) -> None:
        """Ensure the parent directory exists."""
        self.state_file_path.parent.mkdir(parents=True, exist_ok=True)

    def _create_initial_state_file(self) -> None:
        """Create initial state file if it doesn't exist."""
        self._ensure_directory_exists()
        if not self.state_file_path.exists():
            with FileLock(self.lock_file_path):
                with open(self.state_file_path, "w") as f:
                    json.dump(SyncState().to_dict(), f, indent=2)

    def _load_state(self) -> SyncState:
        """Load state from file."""
        self._create_initial_state_file()
        try:
            with open(self.state_file_path, "r") as f:
                data = json.load(f)
                return SyncState.from_dict(data)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning(f"Failed to load state file, starting fresh: {e}")
            return SyncState()

    def _save_state(self, state: SyncState) -> None:
        """Save state to file."""
        self._ensure_directory_exists()
        with FileLock(self.lock_file_path):
            with open(self.state_file_path, "w") as f:
                json.dump(state.to_dict(), f, indent=2)

    @property
    def state(self) -> SyncState:
        """Get current state, loading from file if needed."""
        if self._state is None:
            self._state = self._load_state()
        return self._state

    def is_synced(self, tweet_id: str) -> bool:
        """Check if a tweet has already been synced."""
        return tweet_id in self.state.synced_tweet_ids

    def mark_synced(self, tweet_id: str) -> None:
        """Mark a tweet as synced."""
        self.state.synced_tweet_ids.add(tweet_id)
        self.state.total_synced_count += 1
        self._save_state(self.state)
        logger.debug(f"Marked tweet {tweet_id} as synced")

    def mark_multiple_synced(self, tweet_ids: list[str]) -> None:
        """Mark multiple tweets as synced (more efficient)."""
        for tweet_id in tweet_ids:
            self.state.synced_tweet_ids.add(tweet_id)
        self.state.total_synced_count += len(tweet_ids)
        self._save_state(self.state)
        logger.debug(f"Marked {len(tweet_ids)} tweets as synced")

    def update_last_sync_time(self) -> None:
        """Update the last sync timestamp."""
        self.state.last_sync_time = datetime.utcnow().isoformat()
        self._save_state(self.state)

    def update_last_bookmark_id(self, bookmark_id: str) -> None:
        """Update the last bookmark ID for pagination."""
        self.state.last_bookmark_id = bookmark_id
        self._save_state(self.state)

    def get_stats(self) -> dict:
        """Get sync statistics."""
        return {
            "total_synced": self.state.total_synced_count,
            "unique_tweets": len(self.state.synced_tweet_ids),
            "last_sync": self.state.last_sync_time,
        }

    def clear(self) -> None:
        """Clear all state (use with caution)."""
        self._state = SyncState()
        self._save_state(self._state)
        logger.info("State cleared")

    def reload(self) -> None:
        """Force reload state from file."""
        self._state = self._load_state()
