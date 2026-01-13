"""
Unit tests for the Twitter client module.

Tests Tweet dataclass, TwitterClient API interactions, and OAuth2 flow.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


class TestTweetType:
    """Tests for TweetType enum."""

    def test_tweet_type_values(self):
        """Test TweetType enum has correct values."""
        from twitter_notion_sync.twitter_client import TweetType

        assert TweetType.REGULAR.value == "Regular Tweet"
        assert TweetType.THREAD.value == "Thread"
        assert TweetType.LONG_FORM.value == "Long-form"


class TestTweet:
    """Tests for Tweet dataclass."""

    def test_tweet_creation(self):
        """Test Tweet can be created with all fields."""
        from twitter_notion_sync.twitter_client import Tweet, TweetType

        tweet = Tweet(
            id="123",
            text="Test tweet text",
            author_name="Test Author",
            author_handle="testauthor",
            url="https://twitter.com/testauthor/status/123",
            created_at=datetime(2024, 1, 15, 10, 0, 0),
            bookmarked_at=datetime(2024, 1, 15, 12, 0, 0),
            tweet_type=TweetType.REGULAR,
        )

        assert tweet.id == "123"
        assert tweet.text == "Test tweet text"

    def test_tweet_thread_tweets_default(self):
        """Test thread_tweets defaults to empty list."""
        from twitter_notion_sync.twitter_client import Tweet, TweetType

        tweet = Tweet(
            id="1",
            text="",
            author_name="",
            author_handle="",
            url="",
            created_at=datetime.now(),
            bookmarked_at=None,
            tweet_type=TweetType.REGULAR,
        )

        assert tweet.thread_tweets == []

    def test_tweet_full_text_regular(self, sample_tweet):
        """Test full_text property for regular tweet."""
        assert sample_tweet.full_text == sample_tweet.text

    def test_tweet_full_text_thread(self, sample_thread_tweet):
        """Test full_text property for thread combines all tweets."""
        full_text = sample_thread_tweet.full_text

        assert "first tweet" in full_text.lower()
        assert "second tweet" in full_text.lower()
        assert "third tweet" in full_text.lower()
        assert "---" in full_text  # Thread separator

    def test_tweet_author_display(self, sample_tweet):
        """Test author_display property formatting."""
        assert sample_tweet.author_display == "Test Author (@testauthor)"


class TestTwitterClientInit:
    """Tests for TwitterClient initialization."""

    def test_client_initialization(self, twitter_config):
        """Test TwitterClient initializes correctly."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)

        assert client.config == twitter_config
        assert client._user_id is None
        assert client._rate_limit_remaining == 180

    def test_client_creates_session(self, twitter_config):
        """Test that requests session is created."""
        from twitter_notion_sync.twitter_client import TwitterClient
        import requests

        client = TwitterClient(twitter_config)

        assert isinstance(client._session, requests.Session)


class TestTwitterClientHeaders:
    """Tests for header generation."""

    def test_get_headers(self, twitter_config):
        """Test header generation includes auth token."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)
        headers = client._get_headers()

        assert "Authorization" in headers
        assert twitter_config.oauth2_access_token in headers["Authorization"]
        assert headers["Content-Type"] == "application/json"


class TestTwitterClientRateLimiting:
    """Tests for rate limiting functionality."""

    def test_handle_rate_limit_headers(self, twitter_config):
        """Test rate limit header parsing."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)

        mock_response = Mock()
        mock_response.headers = {
            "x-rate-limit-remaining": "50",
            "x-rate-limit-reset": "1705320000.0"
        }

        client._handle_rate_limit(mock_response)

        assert client._rate_limit_remaining == 50
        assert client._rate_limit_reset == 1705320000.0

    def test_wait_for_rate_limit(self, twitter_config):
        """Test waiting when rate limit is exhausted."""
        from twitter_notion_sync.twitter_client import TwitterClient
        import time

        client = TwitterClient(twitter_config)
        client._rate_limit_remaining = 0
        client._rate_limit_reset = time.time() + 2

        with patch("time.sleep") as mock_sleep:
            client._wait_for_rate_limit()

            mock_sleep.assert_called_once()
            # Should have reset remaining
            assert client._rate_limit_remaining == 180


class TestTwitterClientApiRequests:
    """Tests for API request handling."""

    def test_make_request_success(self, twitter_config):
        """Test successful API request."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)

        with patch.object(client._session, "request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {}
            mock_response.json.return_value = {"data": "test"}
            mock_response.raise_for_status = Mock()
            mock_request.return_value = mock_response

            result = client._make_request("GET", "/test")

            assert result == {"data": "test"}

    def test_make_request_rate_limited(self, twitter_config):
        """Test handling of 429 rate limit response."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)

        with patch.object(client._session, "request") as mock_request:
            # First call rate limited, second succeeds
            mock_429 = Mock()
            mock_429.status_code = 429
            mock_429.headers = {"retry-after": "1"}

            mock_200 = Mock()
            mock_200.status_code = 200
            mock_200.headers = {}
            mock_200.json.return_value = {"data": "success"}
            mock_200.raise_for_status = Mock()

            mock_request.side_effect = [mock_429, mock_200]

            with patch("time.sleep"):
                result = client._make_request("GET", "/test")

            assert result == {"data": "success"}

    def test_make_request_auth_failure(self, twitter_config):
        """Test handling of 401 authentication error."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)

        with patch.object(client._session, "request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.headers = {}
            mock_request.return_value = mock_response

            with pytest.raises(Exception, match="Authentication failed"):
                client._make_request("GET", "/test")

    def test_make_request_retry_on_error(self, twitter_config):
        """Test retry logic on request failure."""
        from twitter_notion_sync.twitter_client import TwitterClient
        import requests

        client = TwitterClient(twitter_config)

        with patch.object(client._session, "request") as mock_request:
            mock_request.side_effect = [
                requests.exceptions.ConnectionError(),
                requests.exceptions.ConnectionError(),
                Mock(
                    status_code=200,
                    headers={},
                    json=Mock(return_value={"data": "ok"}),
                    raise_for_status=Mock()
                )
            ]

            with patch("time.sleep"):
                result = client._make_request("GET", "/test", retry_count=3)

            assert result == {"data": "ok"}
            assert mock_request.call_count == 3


class TestTwitterClientGetUserId:
    """Tests for user ID retrieval."""

    def test_get_user_id(self, twitter_config):
        """Test fetching authenticated user ID."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)

        with patch.object(client, "_make_request") as mock_request:
            mock_request.return_value = {"data": {"id": "user123"}}

            user_id = client.get_user_id()

            assert user_id == "user123"
            assert client._user_id == "user123"

    def test_get_user_id_cached(self, twitter_config):
        """Test user ID is cached after first fetch."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)
        client._user_id = "cached_user"

        with patch.object(client, "_make_request") as mock_request:
            user_id = client.get_user_id()

            assert user_id == "cached_user"
            mock_request.assert_not_called()


class TestTwitterClientParseTweet:
    """Tests for tweet parsing."""

    def test_parse_regular_tweet(self, twitter_config):
        """Test parsing a regular tweet."""
        from twitter_notion_sync.twitter_client import TwitterClient, TweetType

        client = TwitterClient(twitter_config)

        tweet_data = {
            "id": "123456",
            "text": "Test tweet content",
            "author_id": "author1",
            "created_at": "2024-01-15T10:00:00Z"
        }
        users = {
            "author1": {
                "id": "author1",
                "name": "Test Author",
                "username": "testauthor"
            }
        }

        tweet = client._parse_tweet(tweet_data, users)

        assert tweet.id == "123456"
        assert tweet.text == "Test tweet content"
        assert tweet.author_name == "Test Author"
        assert tweet.author_handle == "testauthor"
        assert tweet.tweet_type == TweetType.REGULAR

    def test_parse_tweet_with_note(self, twitter_config):
        """Test parsing long-form tweet with note_tweet."""
        from twitter_notion_sync.twitter_client import TwitterClient, TweetType

        client = TwitterClient(twitter_config)

        tweet_data = {
            "id": "789",
            "text": "Long content",
            "author_id": "a1",
            "created_at": "2024-01-15T10:00:00Z",
            "note_tweet": {"text": "Full long-form content here"}
        }
        users = {"a1": {"name": "Author", "username": "author"}}

        tweet = client._parse_tweet(tweet_data, users)

        assert tweet.tweet_type == TweetType.LONG_FORM

    def test_parse_tweet_reply(self, twitter_config):
        """Test parsing a reply (potential thread)."""
        from twitter_notion_sync.twitter_client import TwitterClient, TweetType

        client = TwitterClient(twitter_config)

        tweet_data = {
            "id": "999",
            "text": "This is a reply",
            "author_id": "a1",
            "created_at": "2024-01-15T10:00:00Z",
            "referenced_tweets": [{"type": "replied_to", "id": "888"}]
        }
        users = {"a1": {"name": "Author", "username": "author"}}

        tweet = client._parse_tweet(tweet_data, users)

        assert tweet.tweet_type == TweetType.THREAD


class TestTwitterClientDetectTweetType:
    """Tests for tweet type detection."""

    def test_detect_regular_tweet(self, twitter_config):
        """Test detecting regular tweet."""
        from twitter_notion_sync.twitter_client import TwitterClient, TweetType

        client = TwitterClient(twitter_config)

        tweet_data = {
            "text": "A short tweet"
        }

        result = client._detect_tweet_type(tweet_data)

        assert result == TweetType.REGULAR

    def test_detect_long_tweet(self, twitter_config):
        """Test detecting long tweet as long-form."""
        from twitter_notion_sync.twitter_client import TwitterClient, TweetType

        client = TwitterClient(twitter_config)

        tweet_data = {
            "text": "A" * 300  # Over 280 chars
        }

        result = client._detect_tweet_type(tweet_data)

        assert result == TweetType.LONG_FORM


class TestTwitterClientFetchBookmarks:
    """Tests for bookmark fetching."""

    def test_fetch_bookmarks_success(self, twitter_config):
        """Test successfully fetching bookmarks."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)
        client._user_id = "user123"

        with patch.object(client, "_make_request") as mock_request:
            mock_request.return_value = {
                "data": [
                    {
                        "id": "t1",
                        "text": "Tweet 1",
                        "author_id": "a1",
                        "created_at": "2024-01-15T10:00:00Z"
                    }
                ],
                "includes": {
                    "users": [{"id": "a1", "name": "Author 1", "username": "author1"}]
                },
                "meta": {"next_token": "next123"}
            }

            tweets, next_token = client.fetch_bookmarks()

            assert len(tweets) == 1
            assert tweets[0].id == "t1"
            assert next_token == "next123"

    def test_fetch_bookmarks_with_pagination(self, twitter_config):
        """Test fetching bookmarks with pagination token."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)
        client._user_id = "user123"

        with patch.object(client, "_make_request") as mock_request:
            mock_request.return_value = {
                "data": [],
                "includes": {"users": []},
                "meta": {}
            }

            client.fetch_bookmarks(pagination_token="prev_token")

            # Check pagination token was passed
            call_args = mock_request.call_args
            assert call_args[1]["params"]["pagination_token"] == "prev_token"


class TestTwitterClientFetchAllBookmarks:
    """Tests for fetching all bookmarks with pagination."""

    def test_fetch_all_bookmarks(self, twitter_config):
        """Test fetching all bookmarks through pagination."""
        from twitter_notion_sync.twitter_client import TwitterClient, TweetType

        client = TwitterClient(twitter_config)
        client._user_id = "user123"

        with patch.object(client, "fetch_bookmarks") as mock_fetch:
            from twitter_notion_sync.twitter_client import Tweet

            # First page
            tweet1 = Tweet(
                id="1", text="T1", author_name="A", author_handle="a",
                url="u1", created_at=datetime.now(), bookmarked_at=None,
                tweet_type=TweetType.REGULAR
            )
            # Second page
            tweet2 = Tweet(
                id="2", text="T2", author_name="A", author_handle="a",
                url="u2", created_at=datetime.now(), bookmarked_at=None,
                tweet_type=TweetType.REGULAR
            )

            mock_fetch.side_effect = [
                ([tweet1], "next_token"),
                ([tweet2], None)
            ]

            tweets = list(client.fetch_all_bookmarks())

            assert len(tweets) == 2
            assert tweets[0].id == "1"
            assert tweets[1].id == "2"

    def test_fetch_all_bookmarks_with_limit(self, twitter_config):
        """Test fetching bookmarks with limit."""
        from twitter_notion_sync.twitter_client import TwitterClient, Tweet, TweetType

        client = TwitterClient(twitter_config)
        client._user_id = "user123"

        with patch.object(client, "fetch_bookmarks") as mock_fetch:
            tweets_batch = [
                Tweet(
                    id=str(i), text=f"T{i}", author_name="A", author_handle="a",
                    url=f"u{i}", created_at=datetime.now(), bookmarked_at=None,
                    tweet_type=TweetType.REGULAR
                )
                for i in range(10)
            ]
            mock_fetch.return_value = (tweets_batch, "next_token")

            tweets = list(client.fetch_all_bookmarks(limit=5))

            assert len(tweets) == 5


class TestOAuth2FlowHelper:
    """Tests for OAuth2 flow helper."""

    def test_oauth2_init(self):
        """Test OAuth2FlowHelper initialization."""
        from twitter_notion_sync.twitter_client import OAuth2FlowHelper

        helper = OAuth2FlowHelper(
            client_id="cid",
            client_secret="csec",
            redirect_uri="http://localhost:3000/callback"
        )

        assert helper.client_id == "cid"
        assert helper.client_secret == "csec"

    def test_get_authorization_url(self):
        """Test authorization URL generation."""
        from twitter_notion_sync.twitter_client import OAuth2FlowHelper

        helper = OAuth2FlowHelper("cid", "csec")
        url = helper.get_authorization_url("state123", "challenge456")

        assert "twitter.com" in url
        assert "client_id=cid" in url
        assert "state=state123" in url
        assert "code_challenge=challenge456" in url

    def test_exchange_code(self):
        """Test authorization code exchange."""
        from twitter_notion_sync.twitter_client import OAuth2FlowHelper

        helper = OAuth2FlowHelper("cid", "csec")

        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = {
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token"
            }
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = helper.exchange_code("auth_code", "verifier")

            assert result["access_token"] == "new_access_token"
            assert result["refresh_token"] == "new_refresh_token"

    def test_refresh_token(self):
        """Test token refresh."""
        from twitter_notion_sync.twitter_client import OAuth2FlowHelper

        helper = OAuth2FlowHelper("cid", "csec")

        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = {
                "access_token": "refreshed_token"
            }
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = helper.refresh_token("old_refresh_token")

            assert result["access_token"] == "refreshed_token"


class TestTwitterClientEnrichThread:
    """Tests for thread enrichment."""

    def test_enrich_non_thread(self, twitter_config, sample_tweet):
        """Test enrich does nothing for non-thread tweets."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)
        result = client.enrich_with_thread(sample_tweet)

        # Should return same tweet unchanged
        assert result is sample_tweet

    def test_enrich_thread_tweet(self, twitter_config, sample_thread_tweet):
        """Test enrich returns thread tweet."""
        from twitter_notion_sync.twitter_client import TwitterClient

        client = TwitterClient(twitter_config)
        result = client.enrich_with_thread(sample_thread_tweet)

        # Current implementation just returns the tweet
        assert result is sample_thread_tweet
