"""
SMS-to-Notion Webhook Service

Receives SMS messages via Twilio, extracts tweet URLs,
fetches tweet data using Twitter's free oEmbed API,
and saves to Notion.

Usage:
    python -m twitter_notion_sync.sms_webhook

Then configure Twilio webhook URL to point to:
    https://your-domain/sms

Security Features:
    - Twilio webhook signature validation
    - Input sanitization for categories
    - Rate limiting per phone number
    - Request timeouts
    - Secure headers

Performance Features:
    - Connection pooling via requests.Session
    - Configurable timeouts
    - Retry logic with exponential backoff
"""

import os
import re
import html
import logging
import functools
import time
from typing import Optional, Tuple
from datetime import datetime
from collections import defaultdict
from flask import Flask, request, Response, g
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
log_level = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============================================================================
# Configuration
# ============================================================================

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')

# Security settings
VALIDATE_TWILIO_SIGNATURE = os.getenv('VALIDATE_TWILIO_SIGNATURE', 'true').lower() == 'true'
ALLOWED_PHONE_NUMBERS = set(
    filter(None, os.getenv('ALLOWED_PHONE_NUMBERS', '').split(','))
)

# Rate limiting settings
RATE_LIMIT_REQUESTS = int(os.getenv('RATE_LIMIT_REQUESTS', '10'))
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '60'))  # seconds

# Performance settings
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '15'))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))

# Notion API headers
NOTION_HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': '2022-06-28',
    'Content-Type': 'application/json'
}

# Tweet URL patterns
TWEET_URL_PATTERNS = [
    r'https?://(?:www\.)?twitter\.com/\w+/status/(\d+)',
    r'https?://(?:www\.)?x\.com/\w+/status/(\d+)',
    r'https?://(?:mobile\.)?twitter\.com/\w+/status/(\d+)',
]

# In-memory rate limiting storage (use Redis in production for multi-instance)
_rate_limit_storage: dict = defaultdict(list)


# ============================================================================
# HTTP Session with Connection Pooling
# ============================================================================

def create_http_session() -> requests.Session:
    """Create a requests session with connection pooling and retry logic."""
    session = requests.Session()

    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10
    )

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


# Global session for reuse
_http_session: Optional[requests.Session] = None


def get_http_session() -> requests.Session:
    """Get or create the global HTTP session."""
    global _http_session
    if _http_session is None:
        _http_session = create_http_session()
    return _http_session


# ============================================================================
# Security Functions
# ============================================================================

def validate_twilio_signature(f):
    """Decorator to validate Twilio webhook signatures."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not VALIDATE_TWILIO_SIGNATURE:
            return f(*args, **kwargs)

        if not TWILIO_AUTH_TOKEN:
            logger.warning("Twilio auth token not configured, skipping validation")
            return f(*args, **kwargs)

        validator = RequestValidator(TWILIO_AUTH_TOKEN)

        # Get the URL and signature
        url = request.url
        signature = request.headers.get('X-Twilio-Signature', '')

        # Validate
        if not validator.validate(url, request.form, signature):
            logger.warning("Invalid Twilio signature from request")
            resp = MessagingResponse()
            resp.message("Unauthorized request.")
            return str(resp), 403

        return f(*args, **kwargs)

    return decorated_function


def check_rate_limit(phone_number: str) -> bool:
    """
    Check if phone number has exceeded rate limit.

    Returns True if allowed, False if rate limited.
    """
    current_time = time.time()
    window_start = current_time - RATE_LIMIT_WINDOW

    # Clean up old entries
    _rate_limit_storage[phone_number] = [
        t for t in _rate_limit_storage[phone_number]
        if t > window_start
    ]

    # Check limit
    if len(_rate_limit_storage[phone_number]) >= RATE_LIMIT_REQUESTS:
        return False

    # Record this request
    _rate_limit_storage[phone_number].append(current_time)
    return True


def check_allowed_number(phone_number: str) -> bool:
    """Check if phone number is in allowed list (if configured)."""
    if not ALLOWED_PHONE_NUMBERS:
        return True  # No whitelist configured, allow all
    return phone_number in ALLOWED_PHONE_NUMBERS


def sanitize_category(category: str) -> str:
    """
    Sanitize category input to prevent injection attacks.

    - Removes HTML/script tags
    - Limits length
    - Allows only alphanumeric and basic punctuation
    """
    if not category:
        return ""

    # HTML escape
    category = html.escape(category)

    # Remove any remaining HTML-like tags
    category = re.sub(r'<[^>]*>', '', category)

    # Allow only alphanumeric, spaces, hyphens, underscores
    category = re.sub(r'[^a-zA-Z0-9\s\-_]', '', category)

    # Limit length
    category = category[:50]

    # Capitalize first letter
    return category.strip().capitalize() if category.strip() else ""


def mask_phone_number(phone_number: str) -> str:
    """Mask phone number for logging (privacy)."""
    if not phone_number or len(phone_number) < 4:
        return "***"
    return f"***{phone_number[-4:]}"


# ============================================================================
# Security Middleware
# ============================================================================

@app.after_request
def add_security_headers(response: Response) -> Response:
    """Add security headers to all responses."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    return response


@app.before_request
def log_request_start():
    """Log request start and set timing."""
    g.request_start_time = time.time()


@app.after_request
def log_request_end(response: Response) -> Response:
    """Log request completion with timing."""
    if hasattr(g, 'request_start_time'):
        duration = time.time() - g.request_start_time
        logger.debug(f"Request completed in {duration:.3f}s - {response.status_code}")
    return response


# ============================================================================
# Core Functions
# ============================================================================

def extract_tweet_url(text: str) -> Optional[str]:
    """Extract tweet URL from text message."""
    for pattern in TWEET_URL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            # Return the full matched URL
            return match.group(0)
    return None


def extract_tweet_id(tweet_url: str) -> Optional[str]:
    """Extract tweet ID from URL."""
    for pattern in TWEET_URL_PATTERNS:
        match = re.search(pattern, tweet_url)
        if match:
            return match.group(1)
    return None


def fetch_tweet_data(tweet_url: str) -> Optional[dict]:
    """
    Fetch tweet data using FXTwitter API.
    Supports regular tweets, threads, and long-form articles.
    No authentication required!

    Uses connection pooling for better performance.
    """
    tweet_id = extract_tweet_id(tweet_url)
    if not tweet_id:
        logger.error(f"Could not extract tweet ID from URL: {tweet_url}")
        return None

    # Extract username from URL
    username_match = re.search(r'(?:twitter\.com|x\.com)/(\w+)/status', tweet_url)
    username = username_match.group(1) if username_match else 'unknown'

    # Use FXTwitter API for full content (including articles)
    fxtwitter_url = f"https://api.fxtwitter.com/{username}/status/{tweet_id}"

    try:
        session = get_http_session()
        response = session.get(fxtwitter_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        tweet = data.get('tweet', {})
        author = tweet.get('author', {})

        # Get author info
        author_name = f"{author.get('name', 'Unknown')} (@{author.get('screen_name', 'unknown')})"

        # Check if this is an article (long-form content)
        article = tweet.get('article')
        if article:
            # Extract full article content from blocks
            title = article.get('title', '')
            blocks = article.get('content', {}).get('blocks', [])

            # Combine all text blocks into full content
            content_parts = []
            for block in blocks:
                text = block.get('text', '')
                block_type = block.get('type', 'unstyled')

                if block_type == 'header-one':
                    content_parts.append(f"\n# {text}\n")
                elif block_type == 'header-two':
                    content_parts.append(f"\n## {text}\n")
                elif block_type == 'header-three':
                    content_parts.append(f"\n### {text}\n")
                elif block_type in ('unordered-list-item', 'ordered-list-item'):
                    content_parts.append(f"\u2022 {text}")
                elif block_type == 'blockquote':
                    content_parts.append(f"> {text}")
                elif text:  # Regular paragraph
                    content_parts.append(text)

            full_text = '\n\n'.join(content_parts)

            return {
                'author': author_name,
                'title': title,
                'text': full_text.strip(),
                'url': tweet_url,
                'type': 'Long-form'
            }
        else:
            # Regular tweet
            tweet_text = tweet.get('text', '')

            return {
                'author': author_name,
                'title': tweet_text[:100] if tweet_text else 'Tweet',
                'text': tweet_text,
                'url': tweet_url,
                'type': 'Regular Tweet'
            }

    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching tweet data from: {tweet_url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error fetching tweet data: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch tweet data: {e}")
        return None


def text_to_notion_blocks(text: str) -> list:
    """Convert text content to Notion blocks (paragraphs, headings, lists)."""
    blocks = []

    # Split by double newlines to get paragraphs
    paragraphs = text.split('\n\n')

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Detect block type based on content
        if para.startswith('# '):
            # Heading 1
            blocks.append({
                'object': 'block',
                'type': 'heading_1',
                'heading_1': {
                    'rich_text': [{'type': 'text', 'text': {'content': para[2:].strip()[:2000]}}]
                }
            })
        elif para.startswith('## '):
            # Heading 2
            blocks.append({
                'object': 'block',
                'type': 'heading_2',
                'heading_2': {
                    'rich_text': [{'type': 'text', 'text': {'content': para[3:].strip()[:2000]}}]
                }
            })
        elif para.startswith('### '):
            # Heading 3
            blocks.append({
                'object': 'block',
                'type': 'heading_3',
                'heading_3': {
                    'rich_text': [{'type': 'text', 'text': {'content': para[4:].strip()[:2000]}}]
                }
            })
        elif para.startswith('> '):
            # Quote
            blocks.append({
                'object': 'block',
                'type': 'quote',
                'quote': {
                    'rich_text': [{'type': 'text', 'text': {'content': para[2:].strip()[:2000]}}]
                }
            })
        elif para.startswith('\u2022 '):
            # Bullet list item
            blocks.append({
                'object': 'block',
                'type': 'bulleted_list_item',
                'bulleted_list_item': {
                    'rich_text': [{'type': 'text', 'text': {'content': para[2:].strip()[:2000]}}]
                }
            })
        else:
            # Regular paragraph - split long text into chunks
            if len(para) > 2000:
                # Split into multiple paragraph blocks for very long paragraphs
                for i in range(0, len(para), 2000):
                    chunk = para[i:i+2000]
                    blocks.append({
                        'object': 'block',
                        'type': 'paragraph',
                        'paragraph': {
                            'rich_text': [{'type': 'text', 'text': {'content': chunk}}]
                        }
                    })
            else:
                blocks.append({
                    'object': 'block',
                    'type': 'paragraph',
                    'paragraph': {
                        'rich_text': [{'type': 'text', 'text': {'content': para}}]
                    }
                })

    # Notion limits to 100 blocks per request
    return blocks[:100]


def add_to_notion(tweet_data: dict, category: str = None) -> bool:
    """Add tweet to Notion database using raw HTTP API with connection pooling."""
    try:
        # Get title (use article title if available, otherwise first 100 chars of text)
        title = tweet_data.get('title', tweet_data['text'][:100])

        # Get content type
        content_type = tweet_data.get('type', 'SMS Import')

        # Build properties (using "Name" as the title property)
        properties = {
            'Name': {
                'title': [{'text': {'content': title[:100]}}]
            },
            'Author': {
                'rich_text': [{'text': {'content': tweet_data['author']}}]
            },
            'URL': {
                'url': tweet_data['url']
            },
            'Bookmarked Date': {
                'date': {'start': datetime.now().isoformat()}
            },
            'Type': {
                'select': {'name': content_type}
            },
            'Status': {
                'select': {'name': 'Unread'}
            },
        }

        # Add category if provided (sanitize it first)
        if category:
            sanitized_category = sanitize_category(category)
            if sanitized_category:
                properties['Category'] = {
                    'select': {'name': sanitized_category}
                }

        # Convert content to Notion blocks for page body
        content_blocks = text_to_notion_blocks(tweet_data['text'])

        # Create page using raw HTTP API with content blocks and connection pooling
        session = get_http_session()
        response = session.post(
            'https://api.notion.com/v1/pages',
            headers=NOTION_HEADERS,
            json={
                'parent': {'database_id': NOTION_DATABASE_ID},
                'properties': properties,
                'children': content_blocks,  # Add content as page body
            },
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 200:
            logger.info(f"Added tweet to Notion: {tweet_data['url']}")
            return True
        else:
            logger.error(f"Notion API error: {response.status_code} - {response.text}")
            return False

    except requests.exceptions.Timeout:
        logger.error("Timeout while adding to Notion")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error adding to Notion: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to add to Notion: {e}")
        return False


def parse_message(body: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse SMS body for tweet URL and optional category.

    Formats supported:
    - Just URL: "https://x.com/user/status/123"
    - URL + category: "https://x.com/user/status/123 tech"
    - Category + URL: "tech https://x.com/user/status/123"
    """
    tweet_url = extract_tweet_url(body)
    category = None

    if tweet_url:
        # Remove URL from body to find category
        remaining = body.replace(tweet_url, '').strip()
        if remaining:
            # Use first word as category (will be sanitized later)
            category = remaining.split()[0].capitalize()

    return tweet_url, category


# ============================================================================
# Webhook Endpoints
# ============================================================================

@app.route('/sms', methods=['POST'])
@validate_twilio_signature
def sms_webhook():
    """Handle incoming SMS from Twilio."""
    # Get message details
    body = request.form.get('Body', '')
    from_number = request.form.get('From', '')

    # Log with masked phone number for privacy
    logger.info(f"Received SMS from {mask_phone_number(from_number)}")

    # Create response
    resp = MessagingResponse()

    # Check if phone number is allowed (if whitelist configured)
    if not check_allowed_number(from_number):
        logger.warning(f"Blocked request from non-whitelisted number: {mask_phone_number(from_number)}")
        resp.message("This service is not available for your phone number.")
        return str(resp)

    # Check rate limit
    if not check_rate_limit(from_number):
        logger.warning(f"Rate limit exceeded for: {mask_phone_number(from_number)}")
        resp.message("Too many requests. Please wait a minute and try again.")
        return str(resp)

    # Parse message
    tweet_url, category = parse_message(body)

    if not tweet_url:
        resp.message("No tweet URL found. Send a tweet link to save it to Notion.")
        return str(resp)

    # Fetch tweet data
    tweet_data = fetch_tweet_data(tweet_url)

    if not tweet_data:
        resp.message("Couldn't fetch tweet data. The tweet might be private or deleted.")
        return str(resp)

    # Add to Notion
    if add_to_notion(tweet_data, category):
        cat_msg = f" [{sanitize_category(category)}]" if category else ""
        # Truncate response text to avoid issues
        preview = tweet_data['text'][:50].replace('\n', ' ')
        resp.message(f"Saved{cat_msg}: {preview}...")
    else:
        resp.message("Failed to save to Notion. Please try again.")

    return str(resp)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'version': '1.1.0'
    }


@app.route('/metrics', methods=['GET'])
def metrics():
    """
    Simple metrics endpoint for monitoring.
    Returns basic operational metrics.
    """
    return {
        'status': 'ok',
        'rate_limit_tracked_numbers': len(_rate_limit_storage),
        'timestamp': datetime.now().isoformat()
    }


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Run the webhook server."""
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Starting SMS webhook server on port {port}")
    logger.info(f"Webhook URL: http://localhost:{port}/sms")
    logger.info(f"Health check: http://localhost:{port}/health")
    logger.info(f"Twilio signature validation: {'enabled' if VALIDATE_TWILIO_SIGNATURE else 'disabled'}")
    logger.info(f"Rate limit: {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW} seconds")
    if ALLOWED_PHONE_NUMBERS:
        logger.info(f"Phone whitelist: {len(ALLOWED_PHONE_NUMBERS)} numbers configured")
    logger.info("Use ngrok or cloudflare tunnel to expose this to the internet")
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    main()
