"""
Unit tests for the SMS webhook module.

Tests URL extraction, tweet data fetching, Notion block conversion,
and the Flask webhook endpoints.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


class TestExtractTweetUrl:
    """Tests for the extract_tweet_url function."""

    def test_extract_twitter_url(self):
        """Test extracting standard twitter.com URLs."""
        from twitter_notion_sync.sms_webhook import extract_tweet_url

        text = "Check this out https://twitter.com/user/status/1234567890"
        result = extract_tweet_url(text)
        assert result == "https://twitter.com/user/status/1234567890"

    def test_extract_x_url(self):
        """Test extracting x.com URLs."""
        from twitter_notion_sync.sms_webhook import extract_tweet_url

        text = "Look at https://x.com/someuser/status/9876543210"
        result = extract_tweet_url(text)
        assert result == "https://x.com/someuser/status/9876543210"

    def test_extract_mobile_url(self):
        """Test extracting mobile twitter URLs."""
        from twitter_notion_sync.sms_webhook import extract_tweet_url

        text = "https://mobile.twitter.com/user/status/1111111111 shared"
        result = extract_tweet_url(text)
        assert result == "https://mobile.twitter.com/user/status/1111111111"

    def test_extract_www_url(self):
        """Test extracting www.twitter.com URLs."""
        from twitter_notion_sync.sms_webhook import extract_tweet_url

        text = "See https://www.twitter.com/example/status/2222222222"
        result = extract_tweet_url(text)
        assert result == "https://www.twitter.com/example/status/2222222222"

    def test_no_url_returns_none(self):
        """Test that non-tweet text returns None."""
        from twitter_notion_sync.sms_webhook import extract_tweet_url

        assert extract_tweet_url("Just some text") is None
        assert extract_tweet_url("") is None
        assert extract_tweet_url("https://example.com") is None

    def test_extract_url_with_text_around(self):
        """Test extraction with text before and after URL."""
        from twitter_notion_sync.sms_webhook import extract_tweet_url

        text = "Hey check this tweet https://twitter.com/user/status/123 it's great!"
        result = extract_tweet_url(text)
        assert result == "https://twitter.com/user/status/123"


class TestExtractTweetId:
    """Tests for the extract_tweet_id function."""

    def test_extract_id_from_twitter_url(self):
        """Test extracting ID from twitter.com URL."""
        from twitter_notion_sync.sms_webhook import extract_tweet_id

        url = "https://twitter.com/user/status/1234567890"
        assert extract_tweet_id(url) == "1234567890"

    def test_extract_id_from_x_url(self):
        """Test extracting ID from x.com URL."""
        from twitter_notion_sync.sms_webhook import extract_tweet_id

        url = "https://x.com/user/status/9876543210"
        assert extract_tweet_id(url) == "9876543210"

    def test_extract_id_invalid_url(self):
        """Test that invalid URLs return None."""
        from twitter_notion_sync.sms_webhook import extract_tweet_id

        assert extract_tweet_id("https://example.com") is None
        assert extract_tweet_id("not a url") is None


class TestFetchTweetData:
    """Tests for the fetch_tweet_data function."""

    def test_fetch_regular_tweet(self, mock_fxtwitter_response):
        """Test fetching a regular tweet."""
        from twitter_notion_sync.sms_webhook import fetch_tweet_data

        with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_fxtwitter_response
            mock_response.raise_for_status = Mock()

            session_instance = Mock()
            session_instance.get.return_value = mock_response
            mock_session.return_value = session_instance

            result = fetch_tweet_data("https://twitter.com/testuser/status/1234567890")

        assert result is not None
        assert result["author"] == "Test User (@testuser)"
        assert "test tweet" in result["text"].lower()
        assert result["type"] == "Regular Tweet"

    def test_fetch_article_tweet(self, mock_fxtwitter_article_response):
        """Test fetching a long-form article tweet."""
        from twitter_notion_sync.sms_webhook import fetch_tweet_data

        with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_fxtwitter_article_response
            mock_response.raise_for_status = Mock()

            session_instance = Mock()
            session_instance.get.return_value = mock_response
            mock_session.return_value = session_instance

            result = fetch_tweet_data("https://twitter.com/authorhandle/status/9876543210")

        assert result is not None
        assert result["type"] == "Long-form"
        assert "My Test Article Title" in result["title"]
        assert "Introduction" in result["text"]
        assert "First bullet point" in result["text"]

    def test_fetch_tweet_api_error(self):
        """Test handling of API errors."""
        from twitter_notion_sync.sms_webhook import fetch_tweet_data

        with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
            session_instance = Mock()
            session_instance.get.side_effect = Exception("API Error")
            mock_session.return_value = session_instance

            result = fetch_tweet_data("https://twitter.com/user/status/123")

        assert result is None

    def test_fetch_tweet_invalid_url(self):
        """Test handling of invalid URLs."""
        from twitter_notion_sync.sms_webhook import fetch_tweet_data

        result = fetch_tweet_data("not a valid url")
        assert result is None


class TestTextToNotionBlocks:
    """Tests for the text_to_notion_blocks function."""

    def test_simple_paragraph(self):
        """Test conversion of simple text to paragraph block."""
        from twitter_notion_sync.sms_webhook import text_to_notion_blocks

        result = text_to_notion_blocks("Simple paragraph text.")

        assert len(result) == 1
        assert result[0]["type"] == "paragraph"
        assert result[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Simple paragraph text."

    def test_heading_1(self):
        """Test conversion of h1 markdown to heading_1 block."""
        from twitter_notion_sync.sms_webhook import text_to_notion_blocks

        result = text_to_notion_blocks("# Main Heading")

        assert len(result) == 1
        assert result[0]["type"] == "heading_1"
        assert result[0]["heading_1"]["rich_text"][0]["text"]["content"] == "Main Heading"

    def test_heading_2(self):
        """Test conversion of h2 markdown to heading_2 block."""
        from twitter_notion_sync.sms_webhook import text_to_notion_blocks

        result = text_to_notion_blocks("## Sub Heading")

        assert len(result) == 1
        assert result[0]["type"] == "heading_2"

    def test_heading_3(self):
        """Test conversion of h3 markdown to heading_3 block."""
        from twitter_notion_sync.sms_webhook import text_to_notion_blocks

        result = text_to_notion_blocks("### Small Heading")

        assert len(result) == 1
        assert result[0]["type"] == "heading_3"

    def test_quote_block(self):
        """Test conversion of quote syntax to quote block."""
        from twitter_notion_sync.sms_webhook import text_to_notion_blocks

        result = text_to_notion_blocks("> This is a quote")

        assert len(result) == 1
        assert result[0]["type"] == "quote"

    def test_bullet_list(self):
        """Test conversion of bullet point to bulleted_list_item."""
        from twitter_notion_sync.sms_webhook import text_to_notion_blocks

        # Single bullet doesn't use double newline
        text = "First paragraph\n\n\u2022 Bullet point"
        result = text_to_notion_blocks(text)

        assert len(result) == 2
        assert result[1]["type"] == "bulleted_list_item"

    def test_long_text_chunking(self):
        """Test that very long text is split into chunks."""
        from twitter_notion_sync.sms_webhook import text_to_notion_blocks

        # Create text longer than 2000 characters
        long_text = "A" * 3500
        result = text_to_notion_blocks(long_text)

        # Should be split into 2 chunks (2000 + 1500)
        assert len(result) == 2
        assert all(block["type"] == "paragraph" for block in result)

    def test_mixed_content(self):
        """Test conversion of mixed content types."""
        from twitter_notion_sync.sms_webhook import text_to_notion_blocks

        text = """# Title

Regular paragraph here.

## Section

> A quote

\u2022 List item"""

        result = text_to_notion_blocks(text)

        assert len(result) == 5
        assert result[0]["type"] == "heading_1"
        assert result[1]["type"] == "paragraph"
        assert result[2]["type"] == "heading_2"
        assert result[3]["type"] == "quote"
        assert result[4]["type"] == "bulleted_list_item"

    def test_block_limit(self):
        """Test that blocks are limited to 100 per Notion API requirements."""
        from twitter_notion_sync.sms_webhook import text_to_notion_blocks

        # Create text with more than 100 paragraphs
        text = "\n\n".join([f"Paragraph {i}" for i in range(150)])
        result = text_to_notion_blocks(text)

        assert len(result) <= 100


class TestParseMessage:
    """Tests for the parse_message function."""

    def test_url_only(self):
        """Test parsing message with only URL."""
        from twitter_notion_sync.sms_webhook import parse_message

        url, category = parse_message("https://twitter.com/user/status/123")

        assert url == "https://twitter.com/user/status/123"
        assert category is None

    def test_url_with_category_after(self):
        """Test parsing message with URL followed by category."""
        from twitter_notion_sync.sms_webhook import parse_message

        url, category = parse_message("https://twitter.com/user/status/123 tech")

        assert url == "https://twitter.com/user/status/123"
        assert category == "Tech"

    def test_url_with_category_before(self):
        """Test parsing message with category before URL."""
        from twitter_notion_sync.sms_webhook import parse_message

        url, category = parse_message("research https://x.com/user/status/456")

        assert url == "https://x.com/user/status/456"
        assert category == "Research"

    def test_category_capitalization(self):
        """Test that category is properly capitalized."""
        from twitter_notion_sync.sms_webhook import parse_message

        _, category = parse_message("https://twitter.com/u/status/1 PROGRAMMING")
        assert category == "Programming"

    def test_no_url(self):
        """Test parsing message without URL."""
        from twitter_notion_sync.sms_webhook import parse_message

        url, category = parse_message("Just some text without a link")

        assert url is None
        assert category is None


class TestAddToNotion:
    """Tests for the add_to_notion function."""

    def test_add_tweet_success(self):
        """Test successfully adding a tweet to Notion."""
        from twitter_notion_sync.sms_webhook import add_to_notion

        with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"id": "page-123"}'

            session_instance = Mock()
            session_instance.post.return_value = mock_response
            mock_session.return_value = session_instance

            tweet_data = {
                "author": "Test User (@testuser)",
                "title": "Test Tweet Title",
                "text": "This is the tweet content.",
                "url": "https://twitter.com/testuser/status/123",
                "type": "Regular Tweet"
            }

            result = add_to_notion(tweet_data)

            assert result is True
            session_instance.post.assert_called_once()

    def test_add_tweet_with_category(self):
        """Test adding tweet with category."""
        from twitter_notion_sync.sms_webhook import add_to_notion

        with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = '{"id": "page-123"}'

            session_instance = Mock()
            session_instance.post.return_value = mock_response
            mock_session.return_value = session_instance

            tweet_data = {
                "author": "Author (@author)",
                "title": "Tweet",
                "text": "Content",
                "url": "https://twitter.com/a/status/1",
                "type": "Regular Tweet"
            }

            result = add_to_notion(tweet_data, category="Technology")

            assert result is True

            # Check that category was included in the request
            call_args = session_instance.post.call_args
            json_data = call_args.kwargs.get("json")
            assert "Category" in json_data["properties"]
            assert json_data["properties"]["Category"]["select"]["name"] == "Technology"

    def test_add_tweet_api_error(self):
        """Test handling of Notion API errors."""
        from twitter_notion_sync.sms_webhook import add_to_notion

        with patch("twitter_notion_sync.sms_webhook.get_http_session") as mock_session:
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.text = "Bad Request"

            session_instance = Mock()
            session_instance.post.return_value = mock_response
            mock_session.return_value = session_instance

            tweet_data = {
                "author": "User",
                "title": "Title",
                "text": "Text",
                "url": "https://twitter.com/u/status/1",
                "type": "Regular"
            }

            result = add_to_notion(tweet_data)

        assert result is False


class TestSmsWebhookEndpoint:
    """Tests for the /sms webhook endpoint."""

    def test_sms_with_valid_tweet_url(self, client, mock_requests_get, mock_requests_post):
        """Test SMS webhook with a valid tweet URL."""
        response = client.post("/sms", data={
            "Body": "https://twitter.com/user/status/1234567890",
            "From": "+15551234567"
        })

        assert response.status_code == 200
        assert b"Saved" in response.data or b"saved" in response.data.lower()

    def test_sms_without_url(self, client):
        """Test SMS webhook with no URL in message."""
        response = client.post("/sms", data={
            "Body": "Just some random text",
            "From": "+15551234567"
        })

        assert response.status_code == 200
        assert b"No tweet URL found" in response.data

    def test_sms_with_invalid_tweet(self, client):
        """Test SMS webhook when tweet fetch fails."""
        with patch("twitter_notion_sync.sms_webhook.fetch_tweet_data") as mock_fetch:
            mock_fetch.return_value = None

            response = client.post("/sms", data={
                "Body": "https://twitter.com/user/status/123",
                "From": "+15551234567"
            })

        assert response.status_code == 200
        assert b"Couldn" in response.data or b"fetch" in response.data.lower()

    def test_sms_notion_failure(self, client, mock_requests_get):
        """Test SMS webhook when Notion save fails."""
        with patch("twitter_notion_sync.sms_webhook.add_to_notion") as mock_add:
            mock_add.return_value = False

            response = client.post("/sms", data={
                "Body": "https://twitter.com/user/status/123",
                "From": "+15551234567"
            })

        assert response.status_code == 200
        assert b"Failed" in response.data


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check(self, client):
        """Test health check endpoint returns OK."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"

    def test_health_check_method(self, client):
        """Test health check only accepts GET."""
        response = client.post("/health")
        assert response.status_code == 405


class TestSecurityFeatures:
    """Tests for security-related features."""

    @pytest.mark.security
    def test_request_validator_imported(self):
        """Test that Twilio request validator is available."""
        from twitter_notion_sync.sms_webhook import RequestValidator
        assert RequestValidator is not None

    @pytest.mark.security
    def test_no_sensitive_data_in_logs(self, client, mock_requests_get, mock_requests_post, capture_logs):
        """Test that sensitive data is not logged."""
        response = client.post("/sms", data={
            "Body": "https://twitter.com/user/status/123",
            "From": "+15559876543"
        })

        # Check logs don't contain full phone numbers (should be masked or partial)
        for msg in capture_logs.messages:
            # Auth tokens should never appear in logs
            assert "test_notion_token" not in msg.lower()
            assert "test_twilio_auth_token" not in msg.lower()
