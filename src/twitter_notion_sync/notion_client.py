"""
Notion API client for managing the bookmarks database.

Handles creating pages in the Notion database with proper schema.
"""

import logging
import time
from datetime import datetime
from typing import Optional
from notion_client import Client
from notion_client.errors import APIResponseError

from .twitter_client import Tweet, TweetType
from .config import NotionConfig

logger = logging.getLogger(__name__)


# Database schema constants
PROPERTY_TITLE = "Title"
PROPERTY_CONTENT = "Content"
PROPERTY_AUTHOR = "Author"
PROPERTY_URL = "URL"
PROPERTY_BOOKMARKED_DATE = "Bookmarked Date"
PROPERTY_TWEET_DATE = "Tweet Date"
PROPERTY_TYPE = "Type"
PROPERTY_STATUS = "Status"

# Default status for new entries
DEFAULT_STATUS = "Unread"


class NotionClient:
    """
    Client for interacting with Notion API.

    Manages adding bookmarked tweets to a Notion database.
    """

    def __init__(self, config: NotionConfig):
        """
        Initialize the Notion client.

        Args:
            config: Notion API configuration
        """
        self.config = config
        self.client = Client(auth=config.token)
        self._database_validated = False

    def _truncate_title(self, text: str, max_length: int = 100) -> str:
        """
        Truncate text for title, keeping it meaningful.

        Args:
            text: Original text
            max_length: Maximum length

        Returns:
            Truncated text with ellipsis if needed
        """
        if len(text) <= max_length:
            return text

        # Try to break at a word boundary
        truncated = text[:max_length - 1]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.7:  # Only break at space if it's not too far back
            truncated = truncated[:last_space]

        return truncated + "…"

    def _format_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        """Format datetime for Notion API."""
        if dt is None:
            return None
        return dt.isoformat()

    def _create_rich_text(self, text: str) -> list[dict]:
        """
        Create rich text blocks for Notion.

        Notion has a 2000 character limit per rich text block,
        so we need to split long content.
        """
        MAX_BLOCK_LENGTH = 2000
        blocks = []

        for i in range(0, len(text), MAX_BLOCK_LENGTH):
            chunk = text[i:i + MAX_BLOCK_LENGTH]
            blocks.append({
                "type": "text",
                "text": {"content": chunk}
            })

        return blocks if blocks else [{"type": "text", "text": {"content": ""}}]

    def validate_database(self) -> bool:
        """
        Validate that the database exists and has the expected schema.

        Returns:
            True if database is valid
        """
        if self._database_validated:
            return True

        try:
            db = self.client.databases.retrieve(self.config.database_id)
            properties = db.get("properties", {})

            # Check required properties exist
            required = [PROPERTY_TITLE, PROPERTY_CONTENT, PROPERTY_URL]
            missing = [prop for prop in required if prop not in properties]

            if missing:
                logger.warning(
                    f"Database is missing properties: {missing}. "
                    "Please run setup_database() to create them."
                )
                return False

            self._database_validated = True
            logger.info("Database schema validated successfully")
            return True

        except APIResponseError as e:
            logger.error(f"Failed to validate database: {e}")
            return False

    def setup_database(self) -> bool:
        """
        Ensure the database has all required properties.

        Note: This updates an existing database to add missing properties.
        The database must already exist and be shared with the integration.

        Returns:
            True if setup successful
        """
        try:
            # Get current database schema
            db = self.client.databases.retrieve(self.config.database_id)
            existing_properties = set(db.get("properties", {}).keys())

            # Define properties to add (only those that don't exist)
            properties_to_add = {}

            if PROPERTY_CONTENT not in existing_properties:
                properties_to_add[PROPERTY_CONTENT] = {"rich_text": {}}

            if PROPERTY_AUTHOR not in existing_properties:
                properties_to_add[PROPERTY_AUTHOR] = {"rich_text": {}}

            if PROPERTY_URL not in existing_properties:
                properties_to_add[PROPERTY_URL] = {"url": {}}

            if PROPERTY_BOOKMARKED_DATE not in existing_properties:
                properties_to_add[PROPERTY_BOOKMARKED_DATE] = {"date": {}}

            if PROPERTY_TWEET_DATE not in existing_properties:
                properties_to_add[PROPERTY_TWEET_DATE] = {"date": {}}

            if PROPERTY_TYPE not in existing_properties:
                properties_to_add[PROPERTY_TYPE] = {
                    "select": {
                        "options": [
                            {"name": "Regular Tweet", "color": "blue"},
                            {"name": "Thread", "color": "green"},
                            {"name": "Long-form", "color": "purple"},
                        ]
                    }
                }

            if PROPERTY_STATUS not in existing_properties:
                properties_to_add[PROPERTY_STATUS] = {
                    "select": {
                        "options": [
                            {"name": "Unread", "color": "red"},
                            {"name": "Read", "color": "yellow"},
                            {"name": "Archived", "color": "gray"},
                        ]
                    }
                }

            if properties_to_add:
                self.client.databases.update(
                    database_id=self.config.database_id,
                    properties=properties_to_add,
                )
                logger.info(f"Added properties to database: {list(properties_to_add.keys())}")

            self._database_validated = True
            return True

        except APIResponseError as e:
            logger.error(f"Failed to setup database: {e}")
            return False

    def add_tweet(self, tweet: Tweet, retry_count: int = 3) -> Optional[str]:
        """
        Add a tweet to the Notion database.

        Args:
            tweet: Tweet object to add
            retry_count: Number of retries on failure

        Returns:
            Page ID if successful, None otherwise
        """
        # Create title
        if tweet.text.strip():
            title = self._truncate_title(tweet.text)
        else:
            title = f"Tweet from @{tweet.author_handle}…"

        # Get full content (includes thread if applicable)
        content = tweet.full_text

        # Build page properties
        properties = {
            PROPERTY_TITLE: {
                "title": [{"text": {"content": title}}]
            },
            PROPERTY_CONTENT: {
                "rich_text": self._create_rich_text(content)
            },
            PROPERTY_AUTHOR: {
                "rich_text": [{"text": {"content": tweet.author_display}}]
            },
            PROPERTY_URL: {
                "url": tweet.url
            },
            PROPERTY_TYPE: {
                "select": {"name": tweet.tweet_type.value}
            },
            PROPERTY_STATUS: {
                "select": {"name": DEFAULT_STATUS}
            },
        }

        # Add dates if available
        if tweet_date := self._format_datetime(tweet.created_at):
            properties[PROPERTY_TWEET_DATE] = {"date": {"start": tweet_date}}

        if tweet.bookmarked_at:
            bookmarked_date = self._format_datetime(tweet.bookmarked_at)
            properties[PROPERTY_BOOKMARKED_DATE] = {"date": {"start": bookmarked_date}}

        # Attempt to create the page with retries
        for attempt in range(retry_count):
            try:
                response = self.client.pages.create(
                    parent={"database_id": self.config.database_id},
                    properties=properties,
                )
                page_id = response["id"]
                logger.info(f"Added tweet {tweet.id} to Notion (page: {page_id})")
                return page_id

            except APIResponseError as e:
                if e.status == 429:
                    # Rate limited - wait and retry
                    wait_time = 2 ** attempt
                    logger.warning(f"Notion rate limit hit. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                elif e.status == 400:
                    # Bad request - likely schema issue
                    logger.error(f"Failed to add tweet {tweet.id}: {e}")
                    return None
                else:
                    logger.error(f"API error adding tweet {tweet.id}: {e}")
                    if attempt < retry_count - 1:
                        time.sleep(2 ** attempt)
                    continue

            except Exception as e:
                logger.error(f"Unexpected error adding tweet {tweet.id}: {e}")
                if attempt < retry_count - 1:
                    time.sleep(2 ** attempt)
                continue

        return None

    def check_tweet_exists(self, tweet_id: str) -> bool:
        """
        Check if a tweet already exists in the database.

        Args:
            tweet_id: Twitter tweet ID

        Returns:
            True if tweet exists in database
        """
        try:
            # Search for pages with matching URL
            url_pattern = f"status/{tweet_id}"

            response = self.client.databases.query(
                database_id=self.config.database_id,
                filter={
                    "property": PROPERTY_URL,
                    "url": {"contains": url_pattern}
                },
                page_size=1,
            )

            return len(response.get("results", [])) > 0

        except APIResponseError as e:
            logger.error(f"Failed to check if tweet exists: {e}")
            return False

    def get_database_stats(self) -> dict:
        """
        Get statistics about the database.

        Returns:
            Dictionary with stats
        """
        try:
            # Count total pages
            response = self.client.databases.query(
                database_id=self.config.database_id,
                page_size=1,
            )

            # Note: This doesn't give exact count, just indicates if there are results
            has_more = response.get("has_more", False)
            results = len(response.get("results", []))

            return {
                "has_entries": results > 0 or has_more,
                "sample_count": results,
            }

        except APIResponseError as e:
            logger.error(f"Failed to get database stats: {e}")
            return {"error": str(e)}


def create_database_template() -> dict:
    """
    Return the template for creating a new Notion database.

    Note: Databases must be created manually in Notion UI,
    but this shows the expected schema.
    """
    return {
        "title": "Twitter Bookmarks",
        "properties": {
            PROPERTY_TITLE: {"title": {}},
            PROPERTY_CONTENT: {"rich_text": {}},
            PROPERTY_AUTHOR: {"rich_text": {}},
            PROPERTY_URL: {"url": {}},
            PROPERTY_BOOKMARKED_DATE: {"date": {}},
            PROPERTY_TWEET_DATE: {"date": {}},
            PROPERTY_TYPE: {
                "select": {
                    "options": [
                        {"name": "Regular Tweet", "color": "blue"},
                        {"name": "Thread", "color": "green"},
                        {"name": "Long-form", "color": "purple"},
                    ]
                }
            },
            PROPERTY_STATUS: {
                "select": {
                    "options": [
                        {"name": "Unread", "color": "red"},
                        {"name": "Read", "color": "yellow"},
                        {"name": "Archived", "color": "gray"},
                    ]
                }
            },
        },
    }
