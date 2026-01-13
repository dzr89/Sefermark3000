"""
Unit tests for the state manager module.

Tests state persistence, tweet tracking, and file locking.
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, Mock


class TestSyncState:
    """Tests for the SyncState dataclass."""

    def test_sync_state_defaults(self):
        """Test SyncState default values."""
        from twitter_notion_sync.state_manager import SyncState

        state = SyncState()

        assert state.synced_tweet_ids == set()
        assert state.last_sync_time is None
        assert state.total_synced_count == 0
        assert state.last_bookmark_id is None

    def test_sync_state_to_dict(self):
        """Test converting SyncState to dictionary."""
        from twitter_notion_sync.state_manager import SyncState

        state = SyncState(
            synced_tweet_ids={"123", "456"},
            last_sync_time="2024-01-15T10:00:00",
            total_synced_count=5,
            last_bookmark_id="789"
        )

        result = state.to_dict()

        assert set(result["synced_tweet_ids"]) == {"123", "456"}
        assert result["last_sync_time"] == "2024-01-15T10:00:00"
        assert result["total_synced_count"] == 5
        assert result["last_bookmark_id"] == "789"

    def test_sync_state_from_dict(self):
        """Test creating SyncState from dictionary."""
        from twitter_notion_sync.state_manager import SyncState

        data = {
            "synced_tweet_ids": ["111", "222", "333"],
            "last_sync_time": "2024-01-20T15:30:00",
            "total_synced_count": 10,
            "last_bookmark_id": "444"
        }

        state = SyncState.from_dict(data)

        assert state.synced_tweet_ids == {"111", "222", "333"}
        assert state.last_sync_time == "2024-01-20T15:30:00"
        assert state.total_synced_count == 10
        assert state.last_bookmark_id == "444"

    def test_sync_state_from_dict_missing_fields(self):
        """Test creating SyncState from partial dictionary."""
        from twitter_notion_sync.state_manager import SyncState

        data = {"last_sync_time": "2024-01-01T00:00:00"}
        state = SyncState.from_dict(data)

        assert state.synced_tweet_ids == set()
        assert state.total_synced_count == 0


class TestStateManagerInit:
    """Tests for StateManager initialization."""

    def test_state_manager_init(self, temp_state_file):
        """Test StateManager initialization."""
        from twitter_notion_sync.state_manager import StateManager

        manager = StateManager(temp_state_file)

        assert manager.state_file_path == temp_state_file
        assert manager.lock_file_path == temp_state_file.with_suffix(".lock")

    def test_state_manager_creates_file(self):
        """Test StateManager creates state file if missing."""
        from twitter_notion_sync.state_manager import StateManager

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "new_state.json"
            manager = StateManager(state_path)

            # Access state to trigger file creation
            _ = manager.state

            assert state_path.exists()


class TestStateManagerPersistence:
    """Tests for state persistence."""

    def test_load_existing_state(self):
        """Test loading existing state from file."""
        from twitter_notion_sync.state_manager import StateManager

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "synced_tweet_ids": ["a1", "b2", "c3"],
                "last_sync_time": "2024-01-15T12:00:00",
                "total_synced_count": 3
            }, f)
            path = Path(f.name)

        try:
            manager = StateManager(path)
            state = manager.state

            assert "a1" in state.synced_tweet_ids
            assert state.total_synced_count == 3
        finally:
            path.unlink()

    def test_save_and_reload_state(self, temp_state_file):
        """Test state persists across manager instances."""
        from twitter_notion_sync.state_manager import StateManager

        # First manager adds tweets
        manager1 = StateManager(temp_state_file)
        manager1.mark_synced("tweet1")
        manager1.mark_synced("tweet2")

        # Second manager should see them
        manager2 = StateManager(temp_state_file)
        assert manager2.is_synced("tweet1")
        assert manager2.is_synced("tweet2")
        assert manager2.state.total_synced_count == 2

    def test_handle_corrupted_state_file(self):
        """Test handling of corrupted state file."""
        from twitter_notion_sync.state_manager import StateManager

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            path = Path(f.name)

        try:
            manager = StateManager(path)
            state = manager.state

            # Should return empty state on corruption
            assert state.synced_tweet_ids == set()
            assert state.total_synced_count == 0
        finally:
            path.unlink()


class TestStateManagerOperations:
    """Tests for state management operations."""

    def test_is_synced_true(self, state_manager):
        """Test is_synced returns True for synced tweets."""
        state_manager.mark_synced("existing_tweet")

        assert state_manager.is_synced("existing_tweet") is True

    def test_is_synced_false(self, state_manager):
        """Test is_synced returns False for unsynced tweets."""
        assert state_manager.is_synced("nonexistent_tweet") is False

    def test_mark_synced(self, state_manager):
        """Test marking a tweet as synced."""
        assert not state_manager.is_synced("new_tweet")

        state_manager.mark_synced("new_tweet")

        assert state_manager.is_synced("new_tweet")
        assert state_manager.state.total_synced_count == 1

    def test_mark_synced_increments_count(self, state_manager):
        """Test that mark_synced increments total count."""
        state_manager.mark_synced("t1")
        state_manager.mark_synced("t2")
        state_manager.mark_synced("t3")

        assert state_manager.state.total_synced_count == 3

    def test_mark_multiple_synced(self, state_manager):
        """Test marking multiple tweets at once."""
        tweets = ["batch1", "batch2", "batch3", "batch4"]
        state_manager.mark_multiple_synced(tweets)

        for tweet_id in tweets:
            assert state_manager.is_synced(tweet_id)

        assert state_manager.state.total_synced_count == 4

    def test_update_last_sync_time(self, state_manager):
        """Test updating last sync timestamp."""
        assert state_manager.state.last_sync_time is None

        state_manager.update_last_sync_time()

        assert state_manager.state.last_sync_time is not None
        # Should be a valid ISO timestamp
        datetime.fromisoformat(state_manager.state.last_sync_time)

    def test_update_last_bookmark_id(self, state_manager):
        """Test updating last bookmark ID for pagination."""
        state_manager.update_last_bookmark_id("bookmark_123")

        assert state_manager.state.last_bookmark_id == "bookmark_123"


class TestStateManagerStats:
    """Tests for state statistics."""

    def test_get_stats_empty(self, state_manager):
        """Test getting stats from empty state."""
        stats = state_manager.get_stats()

        assert stats["total_synced"] == 0
        assert stats["unique_tweets"] == 0
        assert stats["last_sync"] is None

    def test_get_stats_with_data(self, state_manager):
        """Test getting stats with synced tweets."""
        state_manager.mark_synced("t1")
        state_manager.mark_synced("t2")
        state_manager.update_last_sync_time()

        stats = state_manager.get_stats()

        assert stats["total_synced"] == 2
        assert stats["unique_tweets"] == 2
        assert stats["last_sync"] is not None


class TestStateManagerReset:
    """Tests for state reset operations."""

    def test_clear_state(self, state_manager):
        """Test clearing all state."""
        state_manager.mark_synced("t1")
        state_manager.mark_synced("t2")
        state_manager.update_last_sync_time()

        state_manager.clear()

        assert state_manager.state.synced_tweet_ids == set()
        assert state_manager.state.total_synced_count == 0
        assert state_manager.state.last_sync_time is None

    def test_reload_state(self, temp_state_file):
        """Test reloading state from file."""
        from twitter_notion_sync.state_manager import StateManager

        manager = StateManager(temp_state_file)
        manager.mark_synced("original")

        # Manually write new state to file
        with open(temp_state_file, "w") as f:
            json.dump({
                "synced_tweet_ids": ["external_change"],
                "total_synced_count": 99
            }, f)

        # Reload should pick up external changes
        manager.reload()

        assert manager.is_synced("external_change")
        assert not manager.is_synced("original")
        assert manager.state.total_synced_count == 99


class TestStateManagerConcurrency:
    """Tests for concurrent access handling."""

    def test_file_locking_during_save(self, temp_state_file):
        """Test that file locking is used during save operations."""
        from twitter_notion_sync.state_manager import StateManager
        from filelock import FileLock

        manager = StateManager(temp_state_file)

        with patch("twitter_notion_sync.state_manager.FileLock") as MockLock:
            mock_lock_instance = Mock()
            mock_lock_instance.__enter__ = Mock(return_value=None)
            mock_lock_instance.__exit__ = Mock(return_value=None)
            MockLock.return_value = mock_lock_instance

            manager.mark_synced("test")

            MockLock.assert_called()

    def test_concurrent_mark_synced(self, temp_state_file):
        """Test concurrent mark_synced operations."""
        from twitter_notion_sync.state_manager import StateManager
        import threading

        manager = StateManager(temp_state_file)
        results = []

        def mark_many(start_id, count):
            for i in range(count):
                manager.mark_synced(f"tweet_{start_id}_{i}")
                results.append(f"tweet_{start_id}_{i}")

        threads = [
            threading.Thread(target=mark_many, args=(1, 10)),
            threading.Thread(target=mark_many, args=(2, 10)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All tweets should be marked
        for tweet_id in results:
            assert manager.is_synced(tweet_id)


class TestStateManagerEdgeCases:
    """Tests for edge cases and error handling."""

    def test_mark_same_tweet_twice(self, state_manager):
        """Test marking the same tweet twice."""
        state_manager.mark_synced("duplicate")
        state_manager.mark_synced("duplicate")

        # Should only appear once in set
        assert len([t for t in state_manager.state.synced_tweet_ids if t == "duplicate"]) == 1
        # But count should increment twice (current behavior)
        assert state_manager.state.total_synced_count == 2

    def test_empty_tweet_id(self, state_manager):
        """Test handling empty tweet ID."""
        state_manager.mark_synced("")

        assert state_manager.is_synced("")

    def test_very_long_tweet_id(self, state_manager):
        """Test handling very long tweet ID."""
        long_id = "x" * 1000
        state_manager.mark_synced(long_id)

        assert state_manager.is_synced(long_id)

    def test_special_characters_in_tweet_id(self, state_manager):
        """Test handling special characters in tweet ID."""
        special_id = "tweet_123_!@#$%^&*()"
        state_manager.mark_synced(special_id)

        assert state_manager.is_synced(special_id)
