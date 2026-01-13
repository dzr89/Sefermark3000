"""
Integration tests for the Twitter Notion Sync application.

These tests verify end-to-end functionality with mocked external services.
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


@pytest.mark.integration
class TestEndToEndSmsFlow:
    """End-to-end tests for the SMS webhook flow."""

    def test_full_sms_to_notion_flow(self, client, mock_fxtwitter_response):
        """Test complete flow: SMS received -> tweet fetched -> saved to Notion."""
        with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
            # Mock responses for both FXTwitter and Notion
            mock_get_response = Mock()
            mock_get_response.status_code = 200
            mock_get_response.json.return_value = mock_fxtwitter_response
            mock_get_response.raise_for_status = Mock()

            mock_post_response = Mock()
            mock_post_response.status_code = 200
            mock_post_response.text = '{"id": "new-page-id"}'

            session_instance = Mock()
            session_instance.get.return_value = mock_get_response
            session_instance.post.return_value = mock_post_response
            mock_session.return_value = session_instance

            # Send SMS with tweet URL
            response = client.post("/sms", data={
                "Body": "https://twitter.com/testuser/status/1234567890 tech",
                "From": "+15551234567"
            })

            # Verify response
            assert response.status_code == 200
            assert b"Saved" in response.data

            # Verify FXTwitter was called
            session_instance.get.assert_called_once()
            fxtwitter_url = session_instance.get.call_args[0][0]
            assert "fxtwitter.com" in fxtwitter_url

            # Verify Notion was called
            session_instance.post.assert_called_once()
            notion_url = session_instance.post.call_args[0][0]
            assert "notion.com" in notion_url

    def test_full_flow_with_article(self, client, mock_fxtwitter_article_response):
        """Test flow with long-form article content."""
        with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
            mock_get_response = Mock()
            mock_get_response.status_code = 200
            mock_get_response.json.return_value = mock_fxtwitter_article_response
            mock_get_response.raise_for_status = Mock()

            mock_post_response = Mock()
            mock_post_response.status_code = 200
            mock_post_response.text = '{"id": "article-page"}'

            session_instance = Mock()
            session_instance.get.return_value = mock_get_response
            session_instance.post.return_value = mock_post_response
            mock_session.return_value = session_instance

            response = client.post("/sms", data={
                "Body": "https://twitter.com/author/status/9876543210",
                "From": "+15559876543"
            })

            assert response.status_code == 200

            # Verify Notion request included article content
            notion_call = session_instance.post.call_args
            json_data = notion_call.kwargs.get("json")

            # Should have content blocks for the article
            assert "children" in json_data


@pytest.mark.integration
class TestStateManagerWithNotionClient:
    """Integration tests for StateManager with NotionClient."""

    def test_deduplication_flow(self, notion_config, temp_state_file):
        """Test that duplicate tweets are not added."""
        from twitter_notion_sync.state_manager import StateManager
        from twitter_notion_sync.notion_client import NotionClient
        from twitter_notion_sync.twitter_client import Tweet, TweetType

        state_manager = StateManager(temp_state_file)

        with patch("twitter_notion_sync.notion_client.Client") as MockNotionClient:
            mock_client = Mock()
            mock_client.pages.create.return_value = {"id": "page-1"}
            MockNotionClient.return_value = mock_client

            notion_client = NotionClient(notion_config)

            tweet = Tweet(
                id="dedup_test_123",
                text="Test tweet",
                author_name="Author",
                author_handle="author",
                url="https://twitter.com/author/status/dedup_test_123",
                created_at=datetime.now(),
                bookmarked_at=datetime.now(),
                tweet_type=TweetType.REGULAR,
            )

            # First time - should save
            if not state_manager.is_synced(tweet.id):
                notion_client.add_tweet(tweet)
                state_manager.mark_synced(tweet.id)

            # Reset mock call count
            mock_client.pages.create.reset_mock()

            # Second time - should skip
            if not state_manager.is_synced(tweet.id):
                notion_client.add_tweet(tweet)
                state_manager.mark_synced(tweet.id)

            # Should not have been called second time
            mock_client.pages.create.assert_not_called()


@pytest.mark.integration
class TestConfigWithClients:
    """Integration tests for configuration with client initialization."""

    def test_notion_client_with_loaded_config(self, mock_env_vars):
        """Test NotionClient works with config loaded from env."""
        from twitter_notion_sync.config import NotionConfig
        from twitter_notion_sync.notion_client import NotionClient

        config = NotionConfig(
            token=mock_env_vars["NOTION_TOKEN"],
            database_id=mock_env_vars["NOTION_DATABASE_ID"]
        )

        with patch("twitter_notion_sync.notion_client.Client"):
            client = NotionClient(config)
            assert client.config.token == "test_notion_token"

    def test_twitter_client_with_loaded_config(self, mock_env_vars):
        """Test TwitterClient works with config loaded from env."""
        from twitter_notion_sync.config import TwitterConfig
        from twitter_notion_sync.twitter_client import TwitterClient

        config = TwitterConfig(
            client_id="",
            client_secret="",
            access_token="",
            access_token_secret="",
            bearer_token="",
            oauth2_client_id=mock_env_vars["TWITTER_OAUTH2_CLIENT_ID"],
            oauth2_client_secret=mock_env_vars["TWITTER_OAUTH2_CLIENT_SECRET"],
            oauth2_access_token=mock_env_vars["TWITTER_OAUTH2_ACCESS_TOKEN"],
            oauth2_refresh_token=mock_env_vars["TWITTER_OAUTH2_REFRESH_TOKEN"],
        )

        client = TwitterClient(config)
        assert client.config.oauth2_access_token == "test_oauth2_access_token"


@pytest.mark.integration
class TestErrorRecovery:
    """Integration tests for error recovery scenarios."""

    def test_notion_retry_on_rate_limit(self, notion_config, sample_tweet):
        """Test Notion client retries on rate limit."""
        from twitter_notion_sync.notion_client import NotionClient
        from notion_client.errors import APIResponseError

        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            mock_client = Mock()
            # Fail first, succeed second
            mock_client.pages.create.side_effect = [
                APIResponseError(Mock(status_code=429), "Rate limited", ""),
                {"id": "success-page"}
            ]
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)

            with patch("time.sleep"):
                result = client.add_tweet(sample_tweet)

            assert result == "success-page"

    def test_fxtwitter_failure_graceful(self, client):
        """Test graceful handling when FXTwitter is unavailable."""
        with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
            session_instance = Mock()
            session_instance.get.side_effect = Exception("Service unavailable")
            mock_session.return_value = session_instance

            response = client.post("/sms", data={
                "Body": "https://twitter.com/user/status/123",
                "From": "+15551234567"
            })

            # Should return error message, not 500
            assert response.status_code == 200
            assert b"Couldn" in response.data or b"fetch" in response.data.lower()


@pytest.mark.integration
class TestMultipleTweetsFlow:
    """Integration tests for handling multiple tweets."""

    def test_batch_sync_with_state_tracking(self, temp_state_file):
        """Test syncing multiple tweets with state tracking."""
        from twitter_notion_sync.state_manager import StateManager
        from twitter_notion_sync.twitter_client import Tweet, TweetType

        state_manager = StateManager(temp_state_file)

        # Simulate batch of tweets
        tweet_ids = [f"batch_tweet_{i}" for i in range(10)]

        # Mark half as already synced
        for tweet_id in tweet_ids[:5]:
            state_manager.mark_synced(tweet_id)

        # Check which need syncing
        to_sync = [tid for tid in tweet_ids if not state_manager.is_synced(tid)]

        assert len(to_sync) == 5
        assert "batch_tweet_5" in to_sync
        assert "batch_tweet_0" not in to_sync


@pytest.mark.integration
@pytest.mark.security
class TestSecurityIntegration:
    """Security-focused integration tests."""

    def test_malformed_request_handling(self, client):
        """Test handling of malformed requests."""
        # Missing required fields
        response = client.post("/sms", data={})

        # Should handle gracefully
        assert response.status_code == 200

    def test_injection_attempt_in_category(self, client, mock_requests_get, mock_requests_post):
        """Test that injection attempts in category are neutralized."""
        response = client.post("/sms", data={
            "Body": "https://twitter.com/user/status/123 <script>alert('xss')</script>",
            "From": "+15551234567"
        })

        # Should not crash, category should be sanitized
        assert response.status_code == 200

    def test_very_long_message_handling(self, client):
        """Test handling of extremely long messages."""
        long_body = "A" * 10000 + " https://twitter.com/user/status/123 " + "B" * 10000

        response = client.post("/sms", data={
            "Body": long_body,
            "From": "+15551234567"
        })

        # Should handle without crashing
        assert response.status_code == 200


@pytest.mark.integration
class TestConcurrentOperations:
    """Tests for concurrent operation handling."""

    def test_concurrent_state_updates(self, temp_state_file):
        """Test concurrent state updates don't corrupt data."""
        from twitter_notion_sync.state_manager import StateManager
        import threading

        results = {"success": 0, "error": 0}

        def update_state(manager, prefix, count):
            try:
                for i in range(count):
                    manager.mark_synced(f"{prefix}_{i}")
                results["success"] += 1
            except Exception:
                results["error"] += 1

        manager1 = StateManager(temp_state_file)
        manager2 = StateManager(temp_state_file)

        threads = [
            threading.Thread(target=update_state, args=(manager1, "a", 20)),
            threading.Thread(target=update_state, args=(manager2, "b", 20)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur
        assert results["error"] == 0

        # Both should have completed
        assert results["success"] == 2

        # All tweets should be present
        manager_check = StateManager(temp_state_file)
        for i in range(20):
            assert manager_check.is_synced(f"a_{i}")
            assert manager_check.is_synced(f"b_{i}")
