"""
Twitter API client for fetching bookmarks.

Uses Twitter API v2 with OAuth 2.0 for user context operations.
"""

import logging
import time
import requests
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Generator
from enum import Enum

from .config import TwitterConfig

logger = logging.getLogger(__name__)


class TweetType(Enum):
    """Type of tweet content."""
    REGULAR = "Regular Tweet"
    THREAD = "Thread"
    LONG_FORM = "Long-form"


@dataclass
class Tweet:
    """Represents a tweet with all relevant data."""
    id: str
    text: str
    author_name: str
    author_handle: str
    url: str
    created_at: datetime
    bookmarked_at: Optional[datetime]
    tweet_type: TweetType
    thread_tweets: list["Tweet"] = None  # For threads, contains all tweets
    is_truncated: bool = False

    def __post_init__(self):
        if self.thread_tweets is None:
            self.thread_tweets = []

    @property
    def full_text(self) -> str:
        """Get full text, combining thread if applicable."""
        if self.tweet_type == TweetType.THREAD and self.thread_tweets:
            parts = [self.text]
            for tweet in self.thread_tweets:
                parts.append(f"\n\n---\n\n{tweet.text}")
            return "".join(parts)
        return self.text

    @property
    def author_display(self) -> str:
        """Get author in 'Display Name (@handle)' format."""
        return f"{self.author_name} (@{self.author_handle})"


class TwitterClient:
    """
    Client for interacting with Twitter API v2.

    Handles OAuth 2.0 authentication, rate limiting, and pagination.
    """

    BASE_URL = "https://api.twitter.com/2"
    BOOKMARKS_ENDPOINT = "/users/{user_id}/bookmarks"

    # Rate limits for bookmarks endpoint (free tier)
    RATE_LIMIT_REQUESTS = 180
    RATE_LIMIT_WINDOW = 15 * 60  # 15 minutes in seconds

    def __init__(self, config: TwitterConfig):
        """
        Initialize the Twitter client.

        Args:
            config: Twitter API configuration
        """
        self.config = config
        self._user_id: Optional[str] = None
        self._rate_limit_remaining: int = self.RATE_LIMIT_REQUESTS
        self._rate_limit_reset: Optional[float] = None
        self._session = requests.Session()

    def _get_headers(self) -> dict:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.config.oauth2_access_token}",
            "Content-Type": "application/json",
        }

    def _handle_rate_limit(self, response: requests.Response) -> None:
        """Handle rate limit headers from response."""
        if "x-rate-limit-remaining" in response.headers:
            self._rate_limit_remaining = int(response.headers["x-rate-limit-remaining"])
        if "x-rate-limit-reset" in response.headers:
            self._rate_limit_reset = float(response.headers["x-rate-limit-reset"])

        logger.debug(
            f"Rate limit status: {self._rate_limit_remaining} remaining, "
            f"resets at {self._rate_limit_reset}"
        )

    def _wait_for_rate_limit(self) -> None:
        """Wait if we've hit the rate limit."""
        if self._rate_limit_remaining <= 1 and self._rate_limit_reset:
            wait_time = max(0, self._rate_limit_reset - time.time()) + 1
            if wait_time > 0:
                logger.warning(f"Rate limit reached. Waiting {wait_time:.0f} seconds...")
                time.sleep(wait_time)
                self._rate_limit_remaining = self.RATE_LIMIT_REQUESTS

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        retry_count: int = 3,
    ) -> dict:
        """
        Make an API request with retry logic.

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            retry_count: Number of retries on failure

        Returns:
            JSON response data

        Raises:
            Exception: If request fails after retries
        """
        self._wait_for_rate_limit()

        url = f"{self.BASE_URL}{endpoint}"

        for attempt in range(retry_count):
            try:
                response = self._session.request(
                    method,
                    url,
                    headers=self._get_headers(),
                    params=params,
                    timeout=30,
                )

                self._handle_rate_limit(response)

                if response.status_code == 429:
                    # Rate limited - wait and retry
                    wait_time = int(response.headers.get("retry-after", 60))
                    logger.warning(f"Rate limited. Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue

                if response.status_code == 401:
                    raise Exception(
                        "Authentication failed. Please check your OAuth tokens "
                        "and ensure you have completed the OAuth 2.0 flow."
                    )

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{retry_count}): {e}")
                if attempt < retry_count - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise

        raise Exception(f"Failed to complete request after {retry_count} attempts")

    def get_user_id(self) -> str:
        """
        Get the authenticated user's ID.

        Returns:
            User ID string
        """
        if self._user_id:
            return self._user_id

        response = self._make_request("GET", "/users/me")
        self._user_id = response["data"]["id"]
        logger.info(f"Authenticated as user ID: {self._user_id}")
        return self._user_id

    def _parse_tweet(
        self,
        tweet_data: dict,
        users: dict,
        bookmarked_at: Optional[datetime] = None,
    ) -> Tweet:
        """
        Parse a tweet from API response.

        Args:
            tweet_data: Tweet data from API
            users: Dictionary of user data keyed by user ID
            bookmarked_at: When the tweet was bookmarked

        Returns:
            Parsed Tweet object
        """
        author_id = tweet_data.get("author_id")
        author_data = users.get(author_id, {})

        # Parse tweet timestamp
        created_at_str = tweet_data.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except ValueError:
            created_at = datetime.utcnow()

        # Detect tweet type
        tweet_type = self._detect_tweet_type(tweet_data)

        # Check if text is truncated
        is_truncated = tweet_data.get("truncated", False)

        # Build tweet URL
        author_handle = author_data.get("username", "unknown")
        tweet_id = tweet_data["id"]
        url = f"https://twitter.com/{author_handle}/status/{tweet_id}"

        return Tweet(
            id=tweet_id,
            text=tweet_data.get("text", ""),
            author_name=author_data.get("name", "Unknown"),
            author_handle=author_handle,
            url=url,
            created_at=created_at,
            bookmarked_at=bookmarked_at,
            tweet_type=tweet_type,
            is_truncated=is_truncated,
        )

    def _detect_tweet_type(self, tweet_data: dict) -> TweetType:
        """
        Detect the type of tweet (regular, thread, or long-form).

        Args:
            tweet_data: Tweet data from API

        Returns:
            TweetType enum value
        """
        # Check for long-form content (Twitter Notes/Articles)
        # These have note_tweet or extended tweet data
        if tweet_data.get("note_tweet"):
            return TweetType.LONG_FORM

        # Check if tweet is part of a thread by looking at conversation_id
        # and referenced_tweets
        referenced_tweets = tweet_data.get("referenced_tweets", [])
        for ref in referenced_tweets:
            if ref.get("type") == "replied_to":
                # This tweet is a reply - could be part of a thread
                # We'll determine thread status when fetching the conversation
                return TweetType.THREAD

        # Check for long text (typically > 280 chars indicates long-form)
        text = tweet_data.get("text", "")
        if len(text) > 280:
            return TweetType.LONG_FORM

        return TweetType.REGULAR

    def fetch_bookmarks(
        self,
        max_results: int = 100,
        pagination_token: Optional[str] = None,
    ) -> tuple[list[Tweet], Optional[str]]:
        """
        Fetch bookmarked tweets.

        Args:
            max_results: Maximum number of results per page (max 100)
            pagination_token: Token for pagination

        Returns:
            Tuple of (list of tweets, next pagination token)
        """
        user_id = self.get_user_id()
        endpoint = self.BOOKMARKS_ENDPOINT.format(user_id=user_id)

        params = {
            "max_results": min(max_results, 100),
            "tweet.fields": "author_id,created_at,text,conversation_id,referenced_tweets,note_tweet",
            "expansions": "author_id",
            "user.fields": "name,username",
        }

        if pagination_token:
            params["pagination_token"] = pagination_token

        response = self._make_request("GET", endpoint, params=params)

        tweets = []
        data = response.get("data", [])
        includes = response.get("includes", {})

        # Build user lookup dictionary
        users = {user["id"]: user for user in includes.get("users", [])}

        # Current time as bookmark time (API doesn't provide exact bookmark time)
        bookmarked_at = datetime.utcnow()

        for tweet_data in data:
            tweet = self._parse_tweet(tweet_data, users, bookmarked_at)
            tweets.append(tweet)

        # Get next pagination token
        next_token = response.get("meta", {}).get("next_token")

        logger.info(f"Fetched {len(tweets)} bookmarks")
        return tweets, next_token

    def fetch_all_bookmarks(
        self,
        limit: Optional[int] = None,
    ) -> Generator[Tweet, None, None]:
        """
        Fetch all bookmarks using pagination.

        Args:
            limit: Maximum total tweets to fetch (None for all)

        Yields:
            Tweet objects
        """
        pagination_token = None
        total_fetched = 0

        while True:
            tweets, next_token = self.fetch_bookmarks(
                pagination_token=pagination_token
            )

            for tweet in tweets:
                yield tweet
                total_fetched += 1
                if limit and total_fetched >= limit:
                    return

            if not next_token:
                break

            pagination_token = next_token

        logger.info(f"Finished fetching all bookmarks. Total: {total_fetched}")

    def fetch_thread(self, conversation_id: str, author_id: str) -> list[Tweet]:
        """
        Fetch all tweets in a thread/conversation.

        Args:
            conversation_id: The conversation ID
            author_id: The original author's ID

        Returns:
            List of tweets in the thread, ordered chronologically
        """
        endpoint = "/tweets/search/recent"

        params = {
            "query": f"conversation_id:{conversation_id} from:{author_id}",
            "tweet.fields": "author_id,created_at,text,conversation_id",
            "expansions": "author_id",
            "user.fields": "name,username",
            "max_results": 100,
        }

        try:
            response = self._make_request("GET", endpoint, params=params)
        except Exception as e:
            logger.warning(f"Failed to fetch thread {conversation_id}: {e}")
            return []

        tweets = []
        data = response.get("data", [])
        includes = response.get("includes", {})
        users = {user["id"]: user for user in includes.get("users", [])}

        for tweet_data in data:
            tweet = self._parse_tweet(tweet_data, users)
            tweets.append(tweet)

        # Sort by created_at
        tweets.sort(key=lambda t: t.created_at)

        logger.debug(f"Fetched {len(tweets)} tweets in thread {conversation_id}")
        return tweets

    def enrich_with_thread(self, tweet: Tweet) -> Tweet:
        """
        If a tweet is part of a thread, fetch the full thread.

        Args:
            tweet: The original tweet

        Returns:
            Tweet with thread_tweets populated if applicable
        """
        if tweet.tweet_type != TweetType.THREAD:
            return tweet

        # Note: This requires additional API calls and may hit rate limits
        # For MVP, we'll just mark it as a thread without fetching
        logger.debug(f"Tweet {tweet.id} is part of a thread")
        return tweet


class OAuth2FlowHelper:
    """
    Helper for completing the OAuth 2.0 PKCE flow for Twitter.

    This is needed for initial setup to get the access token.
    """

    AUTH_URL = "https://twitter.com/i/oauth2/authorize"
    TOKEN_URL = "https://api.twitter.com/2/oauth2/token"

    SCOPES = [
        "tweet.read",
        "users.read",
        "bookmark.read",
        "offline.access",
    ]

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str = "http://localhost:3000/callback"):
        """
        Initialize OAuth2 flow helper.

        Args:
            client_id: Twitter OAuth 2.0 Client ID
            client_secret: Twitter OAuth 2.0 Client Secret
            redirect_uri: Redirect URI configured in Twitter app
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self, state: str, code_challenge: str) -> str:
        """
        Get the authorization URL for user to visit.

        Args:
            state: Random state string for CSRF protection
            code_challenge: PKCE code challenge

        Returns:
            Authorization URL
        """
        import urllib.parse

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> dict:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from callback
            code_verifier: PKCE code verifier

        Returns:
            Token response with access_token and refresh_token
        """
        import base64

        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
        }

        response = requests.post(self.TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()
        return response.json()

    def refresh_token(self, refresh_token: str) -> dict:
        """
        Refresh the access token.

        Args:
            refresh_token: Refresh token

        Returns:
            New token response
        """
        import base64

        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        response = requests.post(self.TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()
        return response.json()
