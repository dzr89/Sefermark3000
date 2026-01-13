"""
Shared pytest fixtures and configuration for the test suite.

This module provides common fixtures for mocking external APIs,
creating test data, and managing test environment setup.
"""

import os
import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch

# Ensure we don't accidentally use real API credentials during tests
os.environ.setdefault("NOTION_TOKEN", "test_notion_token_12345")
os.environ.setdefault("NOTION_DATABASE_ID", "test_database_id_123456789")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_twilio_auth_token")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "test_twilio_account_sid")

# Disable Twilio signature validation in tests
os.environ["VALIDATE_TWILIO_SIGNATURE"] = "false"


# ============================================================================
# Flask Test Client Fixtures
# ============================================================================

@pytest.fixture
def app():
    """Create Flask test application with test configuration."""
    # Ensure signature validation is disabled before importing
    os.environ["VALIDATE_TWILIO_SIGNATURE"] = "false"

    # Need to reload the module to pick up the env var
    import importlib
    import twitter_notion_sync.sms_webhook as webhook_module
    importlib.reload(webhook_module)

    flask_app = webhook_module.app

    flask_app.config.update({
        "TESTING": True,
        "DEBUG": False,
    })

    return flask_app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create Flask CLI test runner."""
    return app.test_cli_runner()


# ============================================================================
# Mock External API Fixtures
# ============================================================================

@pytest.fixture
def mock_fxtwitter_response():
    """Mock FXTwitter API response for a regular tweet."""
    return {
        "tweet": {
            "id": "1234567890",
            "text": "This is a test tweet with some content that we want to save.",
            "author": {
                "name": "Test User",
                "screen_name": "testuser"
            },
            "created_at": "2024-01-15T10:30:00Z"
        }
    }


@pytest.fixture
def mock_fxtwitter_article_response():
    """Mock FXTwitter API response for a long-form article."""
    return {
        "tweet": {
            "id": "9876543210",
            "text": "Check out my new article!",
            "author": {
                "name": "Author Name",
                "screen_name": "authorhandle"
            },
            "created_at": "2024-01-20T14:00:00Z",
            "article": {
                "title": "My Test Article Title",
                "content": {
                    "blocks": [
                        {"type": "header-one", "text": "Introduction"},
                        {"type": "unstyled", "text": "This is the first paragraph of the article."},
                        {"type": "header-two", "text": "Main Section"},
                        {"type": "unstyled", "text": "More content here with details."},
                        {"type": "blockquote", "text": "An important quote from someone."},
                        {"type": "unordered-list-item", "text": "First bullet point"},
                        {"type": "unordered-list-item", "text": "Second bullet point"},
                    ]
                }
            }
        }
    }


@pytest.fixture
def mock_notion_success_response():
    """Mock successful Notion API response."""
    return {
        "object": "page",
        "id": "notion-page-id-123",
        "created_time": "2024-01-15T10:30:00.000Z",
        "properties": {}
    }


@pytest.fixture
def mock_requests_get(mock_fxtwitter_response):
    """Mock requests.get for FXTwitter API calls via session."""
    with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_fxtwitter_response
        mock_response.raise_for_status = Mock()

        session_instance = Mock()
        session_instance.get.return_value = mock_response
        session_instance.post.return_value = mock_response
        mock_session.return_value = session_instance
        yield mock_session


@pytest.fixture
def mock_requests_post(mock_notion_success_response):
    """Mock requests.post for Notion API calls via session."""
    with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_notion_success_response
        mock_response.text = json.dumps(mock_notion_success_response)

        session_instance = Mock()
        session_instance.post.return_value = mock_response
        session_instance.get.return_value = mock_response
        mock_session.return_value = session_instance
        yield mock_session


# ============================================================================
# State Manager Test Fixtures
# ============================================================================

@pytest.fixture
def temp_state_file():
    """Create a temporary state file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        initial_state = {
            "synced_tweet_ids": [],
            "last_sync_time": None,
            "total_synced_count": 0,
            "last_bookmark_id": None
        }
        json.dump(initial_state, f)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()
    lock_path = temp_path.with_suffix(".lock")
    if lock_path.exists():
        lock_path.unlink()


@pytest.fixture
def state_manager(temp_state_file):
    """Create a StateManager instance with temporary file."""
    from twitter_notion_sync.state_manager import StateManager
    return StateManager(temp_state_file)


# ============================================================================
# Twitter Client Test Fixtures
# ============================================================================

@pytest.fixture
def twitter_config():
    """Create a mock Twitter configuration."""
    from twitter_notion_sync.config import TwitterConfig
    return TwitterConfig(
        client_id="test_client_id",
        client_secret="test_client_secret",
        access_token="test_access_token",
        access_token_secret="test_access_token_secret",
        bearer_token="test_bearer_token",
        oauth2_client_id="test_oauth2_client_id",
        oauth2_client_secret="test_oauth2_client_secret",
        oauth2_access_token="test_oauth2_access_token",
        oauth2_refresh_token="test_oauth2_refresh_token",
    )


@pytest.fixture
def notion_config():
    """Create a mock Notion configuration."""
    from twitter_notion_sync.config import NotionConfig
    return NotionConfig(
        token="test_notion_token",
        database_id="test_database_id",
    )


@pytest.fixture
def sample_tweet():
    """Create a sample Tweet object for testing."""
    from twitter_notion_sync.twitter_client import Tweet, TweetType
    return Tweet(
        id="1234567890",
        text="This is a sample tweet for testing purposes.",
        author_name="Test Author",
        author_handle="testauthor",
        url="https://twitter.com/testauthor/status/1234567890",
        created_at=datetime(2024, 1, 15, 10, 30, 0),
        bookmarked_at=datetime(2024, 1, 15, 12, 0, 0),
        tweet_type=TweetType.REGULAR,
    )


@pytest.fixture
def sample_thread_tweet():
    """Create a sample thread Tweet object for testing."""
    from twitter_notion_sync.twitter_client import Tweet, TweetType

    thread_tweets = [
        Tweet(
            id="1234567891",
            text="This is the second tweet in the thread.",
            author_name="Test Author",
            author_handle="testauthor",
            url="https://twitter.com/testauthor/status/1234567891",
            created_at=datetime(2024, 1, 15, 10, 31, 0),
            bookmarked_at=None,
            tweet_type=TweetType.REGULAR,
        ),
        Tweet(
            id="1234567892",
            text="This is the third tweet in the thread.",
            author_name="Test Author",
            author_handle="testauthor",
            url="https://twitter.com/testauthor/status/1234567892",
            created_at=datetime(2024, 1, 15, 10, 32, 0),
            bookmarked_at=None,
            tweet_type=TweetType.REGULAR,
        ),
    ]

    return Tweet(
        id="1234567890",
        text="This is the first tweet in a thread.",
        author_name="Test Author",
        author_handle="testauthor",
        url="https://twitter.com/testauthor/status/1234567890",
        created_at=datetime(2024, 1, 15, 10, 30, 0),
        bookmarked_at=datetime(2024, 1, 15, 12, 0, 0),
        tweet_type=TweetType.THREAD,
        thread_tweets=thread_tweets,
    )


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def valid_tweet_urls():
    """List of valid tweet URLs for testing."""
    return [
        "https://twitter.com/user/status/1234567890",
        "https://x.com/user/status/1234567890",
        "https://www.twitter.com/user/status/1234567890",
        "https://mobile.twitter.com/user/status/1234567890",
        "http://twitter.com/user/status/1234567890",
    ]


@pytest.fixture
def invalid_tweet_urls():
    """List of invalid tweet URLs for testing."""
    return [
        "https://example.com/user/status/1234567890",
        "https://twitter.com/user/likes",
        "https://twitter.com/user",
        "not a url at all",
        "",
        "https://instagram.com/p/ABC123",
    ]


@pytest.fixture
def sms_messages_with_categories():
    """SMS messages with various category formats."""
    return [
        ("https://twitter.com/user/status/123 tech", "https://twitter.com/user/status/123", "Tech"),
        ("tech https://x.com/user/status/456", "https://x.com/user/status/456", "Tech"),
        ("https://twitter.com/user/status/789 RESEARCH", "https://twitter.com/user/status/789", "Research"),
        ("https://twitter.com/user/status/000", "https://twitter.com/user/status/000", None),
    ]


# ============================================================================
# Environment and Configuration Fixtures
# ============================================================================

@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up mock environment variables for testing."""
    env_vars = {
        "NOTION_TOKEN": "test_notion_token",
        "NOTION_DATABASE_ID": "test_database_id",
        "TWILIO_AUTH_TOKEN": "test_twilio_token",
        "TWILIO_ACCOUNT_SID": "test_twilio_sid",
        "TWILIO_PHONE_NUMBER": "+15551234567",
        "TWITTER_OAUTH2_CLIENT_ID": "test_oauth2_client_id",
        "TWITTER_OAUTH2_CLIENT_SECRET": "test_oauth2_client_secret",
        "TWITTER_OAUTH2_ACCESS_TOKEN": "test_oauth2_access_token",
        "TWITTER_OAUTH2_REFRESH_TOKEN": "test_oauth2_refresh_token",
        "PORT": "5000",
        "LOG_LEVEL": "DEBUG",
    }

    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)

    return env_vars


@pytest.fixture
def temp_env_file():
    """Create a temporary .env file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("NOTION_TOKEN=test_token_from_file\n")
        f.write("NOTION_DATABASE_ID=test_db_id_from_file\n")
        f.write("TWITTER_OAUTH2_CLIENT_ID=oauth2_client_id\n")
        f.write("TWITTER_OAUTH2_CLIENT_SECRET=oauth2_client_secret\n")
        f.write("TWITTER_OAUTH2_ACCESS_TOKEN=oauth2_access_token\n")
        f.write("TWITTER_OAUTH2_REFRESH_TOKEN=oauth2_refresh_token\n")
        temp_path = Path(f.name)

    yield temp_path

    if temp_path.exists():
        temp_path.unlink()


# ============================================================================
# Utility Functions
# ============================================================================

@pytest.fixture
def capture_logs():
    """Capture log messages during tests."""
    import logging

    class LogCapture:
        def __init__(self):
            self.records = []

        def __call__(self, record):
            self.records.append(record)
            return True

        @property
        def messages(self):
            return [r.getMessage() for r in self.records]

        def has_message(self, substring):
            return any(substring in msg for msg in self.messages)

    capture = LogCapture()

    # Add filter to root logger
    root_logger = logging.getLogger()
    root_logger.addFilter(capture)

    yield capture

    root_logger.removeFilter(capture)


# ============================================================================
# Markers Configuration
# ============================================================================

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "security: marks tests related to security features"
    )
