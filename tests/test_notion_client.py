"""
Unit tests for the Notion client module.

Tests the NotionClient class methods for database operations,
tweet adding, and schema management.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


class TestNotionClientInit:
    """Tests for NotionClient initialization."""

    def test_client_initialization(self, notion_config):
        """Test NotionClient initializes correctly."""
        with patch("twitter_notion_sync.notion_client.Client"):
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)

            assert client.config == notion_config
            assert client._database_validated is False

    def test_client_creates_notion_client(self, notion_config):
        """Test that underlying Notion client is created."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)

            MockClient.assert_called_once_with(auth=notion_config.token)


class TestTruncateTitle:
    """Tests for the _truncate_title method."""

    def test_short_title_unchanged(self, notion_config):
        """Test short titles are not modified."""
        with patch("twitter_notion_sync.notion_client.Client"):
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)
            result = client._truncate_title("Short title")

            assert result == "Short title"

    def test_long_title_truncated(self, notion_config):
        """Test long titles are truncated."""
        with patch("twitter_notion_sync.notion_client.Client"):
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)
            long_title = "A" * 150
            result = client._truncate_title(long_title)

            assert len(result) <= 100
            assert result.endswith("\u2026")

    def test_truncate_at_word_boundary(self, notion_config):
        """Test truncation respects word boundaries when possible."""
        with patch("twitter_notion_sync.notion_client.Client"):
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)
            title = "This is a very long title that should be truncated at a word boundary somewhere around here"
            result = client._truncate_title(title, max_length=50)

            # Should end at a word boundary (not cut mid-word)
            assert len(result) <= 50
            assert result.endswith("\u2026")


class TestFormatDatetime:
    """Tests for the _format_datetime method."""

    def test_format_datetime(self, notion_config):
        """Test datetime formatting."""
        with patch("twitter_notion_sync.notion_client.Client"):
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)
            dt = datetime(2024, 1, 15, 10, 30, 0)
            result = client._format_datetime(dt)

            assert result == "2024-01-15T10:30:00"

    def test_format_none_datetime(self, notion_config):
        """Test formatting None returns None."""
        with patch("twitter_notion_sync.notion_client.Client"):
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)
            result = client._format_datetime(None)

            assert result is None


class TestCreateRichText:
    """Tests for the _create_rich_text method."""

    def test_short_text(self, notion_config):
        """Test short text creates single block."""
        with patch("twitter_notion_sync.notion_client.Client"):
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)
            result = client._create_rich_text("Short text")

            assert len(result) == 1
            assert result[0]["type"] == "text"
            assert result[0]["text"]["content"] == "Short text"

    def test_long_text_split(self, notion_config):
        """Test long text is split into chunks."""
        with patch("twitter_notion_sync.notion_client.Client"):
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)
            long_text = "A" * 5000
            result = client._create_rich_text(long_text)

            # Should be split into 3 chunks (2000 + 2000 + 1000)
            assert len(result) == 3
            assert all(block["type"] == "text" for block in result)
            assert len(result[0]["text"]["content"]) == 2000

    def test_empty_text(self, notion_config):
        """Test empty text creates single empty block."""
        with patch("twitter_notion_sync.notion_client.Client"):
            from twitter_notion_sync.notion_client import NotionClient

            client = NotionClient(notion_config)
            result = client._create_rich_text("")

            assert len(result) == 1
            assert result[0]["text"]["content"] == ""


class TestValidateDatabase:
    """Tests for the validate_database method."""

    def test_validate_success(self, notion_config):
        """Test successful database validation."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.databases.retrieve.return_value = {
                "properties": {
                    "Title": {},
                    "Content": {},
                    "URL": {}
                }
            }
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.validate_database()

            assert result is True
            assert client._database_validated is True

    def test_validate_missing_properties(self, notion_config):
        """Test validation fails when properties missing."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.databases.retrieve.return_value = {
                "properties": {
                    "Title": {}
                    # Missing Content and URL
                }
            }
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.validate_database()

            assert result is False

    def test_validate_caches_result(self, notion_config):
        """Test validation result is cached."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.databases.retrieve.return_value = {
                "properties": {"Title": {}, "Content": {}, "URL": {}}
            }
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            client.validate_database()
            client.validate_database()

            # Should only call retrieve once due to caching
            assert mock_client.databases.retrieve.call_count == 1

    def test_validate_api_error(self, notion_config):
        """Test validation handles API errors."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient
            from notion_client.errors import APIResponseError

            mock_client = Mock()
            mock_client.databases.retrieve.side_effect = APIResponseError(
                Mock(status_code=404), "Not Found", ""
            )
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.validate_database()

            assert result is False


class TestSetupDatabase:
    """Tests for the setup_database method."""

    def test_setup_adds_missing_properties(self, notion_config):
        """Test setup adds missing properties."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.databases.retrieve.return_value = {
                "properties": {
                    "Title": {}  # Only Title exists
                }
            }
            mock_client.databases.update.return_value = {}
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.setup_database()

            assert result is True
            mock_client.databases.update.assert_called_once()

    def test_setup_no_update_needed(self, notion_config):
        """Test setup doesn't update when all properties exist."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.databases.retrieve.return_value = {
                "properties": {
                    "Title": {},
                    "Content": {},
                    "Author": {},
                    "URL": {},
                    "Bookmarked Date": {},
                    "Tweet Date": {},
                    "Type": {},
                    "Status": {}
                }
            }
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.setup_database()

            assert result is True
            mock_client.databases.update.assert_not_called()


class TestAddTweet:
    """Tests for the add_tweet method."""

    def test_add_tweet_success(self, notion_config, sample_tweet):
        """Test successfully adding a tweet."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.pages.create.return_value = {"id": "page-123"}
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.add_tweet(sample_tweet)

            assert result == "page-123"
            mock_client.pages.create.assert_called_once()

    def test_add_tweet_with_empty_text(self, notion_config):
        """Test adding tweet with empty text uses fallback title."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient
            from twitter_notion_sync.twitter_client import Tweet, TweetType

            mock_client = Mock()
            mock_client.pages.create.return_value = {"id": "page-456"}
            MockClient.return_value = mock_client

            tweet = Tweet(
                id="123",
                text="",
                author_name="Author",
                author_handle="author",
                url="https://twitter.com/author/status/123",
                created_at=datetime.now(),
                bookmarked_at=None,
                tweet_type=TweetType.REGULAR,
            )

            client = NotionClient(notion_config)
            result = client.add_tweet(tweet)

            assert result == "page-456"
            # Check fallback title was used
            call_args = mock_client.pages.create.call_args
            properties = call_args.kwargs["properties"]
            assert "@author" in properties["Title"]["title"][0]["text"]["content"]

    def test_add_tweet_rate_limit_retry(self, notion_config, sample_tweet):
        """Test retry on rate limit."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient
            from notion_client.errors import APIResponseError

            mock_client = Mock()
            # First call rate limited, second succeeds
            mock_client.pages.create.side_effect = [
                APIResponseError(Mock(status_code=429), "Rate limited", ""),
                {"id": "page-789"}
            ]
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)

            with patch("time.sleep"):  # Don't actually sleep
                result = client.add_tweet(sample_tweet)

            assert result == "page-789"
            assert mock_client.pages.create.call_count == 2

    def test_add_tweet_bad_request(self, notion_config, sample_tweet):
        """Test handling of bad request error."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient
            from notion_client.errors import APIResponseError

            mock_client = Mock()
            mock_client.pages.create.side_effect = APIResponseError(
                Mock(status_code=400), "Bad Request", ""
            )
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.add_tweet(sample_tweet)

            assert result is None


class TestCheckTweetExists:
    """Tests for the check_tweet_exists method."""

    def test_tweet_exists(self, notion_config):
        """Test checking for existing tweet."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.databases.query.return_value = {
                "results": [{"id": "existing-page"}]
            }
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.check_tweet_exists("1234567890")

            assert result is True

    def test_tweet_not_exists(self, notion_config):
        """Test checking for non-existing tweet."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.databases.query.return_value = {"results": []}
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.check_tweet_exists("9999999999")

            assert result is False

    def test_check_exists_api_error(self, notion_config):
        """Test check_exists handles API errors gracefully."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient
            from notion_client.errors import APIResponseError

            mock_client = Mock()
            mock_client.databases.query.side_effect = APIResponseError(
                Mock(status_code=500), "Server Error", ""
            )
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            result = client.check_tweet_exists("123")

            # Should return False on error (safe default)
            assert result is False


class TestGetDatabaseStats:
    """Tests for the get_database_stats method."""

    def test_get_stats_with_entries(self, notion_config):
        """Test getting stats from database with entries."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.databases.query.return_value = {
                "results": [{"id": "page1"}],
                "has_more": True
            }
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            stats = client.get_database_stats()

            assert stats["has_entries"] is True
            assert stats["sample_count"] == 1

    def test_get_stats_empty_database(self, notion_config):
        """Test getting stats from empty database."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient

            mock_client = Mock()
            mock_client.databases.query.return_value = {
                "results": [],
                "has_more": False
            }
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            stats = client.get_database_stats()

            assert stats["has_entries"] is False

    def test_get_stats_api_error(self, notion_config):
        """Test stats handles API errors."""
        with patch("twitter_notion_sync.notion_client.Client") as MockClient:
            from twitter_notion_sync.notion_client import NotionClient
            from notion_client.errors import APIResponseError

            mock_client = Mock()
            mock_client.databases.query.side_effect = APIResponseError(
                Mock(status_code=500), "Error", ""
            )
            MockClient.return_value = mock_client

            client = NotionClient(notion_config)
            stats = client.get_database_stats()

            assert "error" in stats


class TestCreateDatabaseTemplate:
    """Tests for the create_database_template function."""

    def test_template_structure(self):
        """Test database template has correct structure."""
        from twitter_notion_sync.notion_client import create_database_template

        template = create_database_template()

        assert "title" in template
        assert "properties" in template
        assert "Title" in template["properties"]
        assert "Content" in template["properties"]
        assert "URL" in template["properties"]
        assert "Type" in template["properties"]
        assert "Status" in template["properties"]

    def test_template_type_options(self):
        """Test Type property has correct options."""
        from twitter_notion_sync.notion_client import create_database_template

        template = create_database_template()
        type_options = template["properties"]["Type"]["select"]["options"]

        option_names = [opt["name"] for opt in type_options]
        assert "Regular Tweet" in option_names
        assert "Thread" in option_names
        assert "Long-form" in option_names

    def test_template_status_options(self):
        """Test Status property has correct options."""
        from twitter_notion_sync.notion_client import create_database_template

        template = create_database_template()
        status_options = template["properties"]["Status"]["select"]["options"]

        option_names = [opt["name"] for opt in status_options]
        assert "Unread" in option_names
        assert "Read" in option_names
        assert "Archived" in option_names
