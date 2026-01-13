# Sefermark3000: Twitter Bookmarks to Notion Sync

An automated service that syncs your Twitter bookmarks to a Notion database. Runs as a background service, polling for new bookmarks and adding them to your Notion workspace.

## Features

- **Automatic sync**: Polls Twitter every 10-15 minutes for new bookmarks
- **One-way sync**: Twitter → Notion only (unbookmarking doesn't remove from Notion)
- **Duplicate prevention**: Tracks synced tweets locally to avoid duplicates
- **Thread detection**: Identifies and labels threads
- **Long-form detection**: Detects Twitter Notes/Articles and long tweets
- **Rate limit handling**: Gracefully handles API rate limits
- **Backfill support**: Sync existing bookmarks on initial setup
- **macOS background service**: Runs automatically using launchd

## Requirements

- Python 3.9+
- Twitter Developer Account (free tier works)
- Notion Integration

## Quick Start

### 1. Clone and Install Dependencies

```bash
git clone https://github.com/yourusername/Sefermark3000.git
cd Sefermark3000

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Set Up Twitter API

1. Go to [Twitter Developer Portal](https://developer.twitter.com/)
2. Create a new project and app
3. Enable OAuth 2.0 with these settings:
   - Type: Confidential client
   - Callback URL: `http://localhost:3000/callback`
4. Request access to these scopes:
   - `tweet.read`
   - `users.read`
   - `bookmark.read`
   - `offline.access`

Run the OAuth setup helper:

```bash
cd src
python -m twitter_notion_sync.oauth_setup
```

Follow the prompts to authorize and get your tokens.

### 3. Set Up Notion Integration

1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Create a new integration with these capabilities:
   - Read content
   - Insert content
   - Update content
3. Copy the integration token

4. Create a new Notion database with a "Title" column

5. Share the database with your integration:
   - Open the database in Notion
   - Click "Share" → "Invite"
   - Select your integration

6. Get the database ID from the URL:
   ```
   https://www.notion.so/yourworkspace/DATABASE_ID?v=...
   ```

### 4. Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# Twitter OAuth 2.0 (from oauth_setup.py)
TWITTER_OAUTH2_CLIENT_ID=your_client_id
TWITTER_OAUTH2_CLIENT_SECRET=your_client_secret
TWITTER_OAUTH2_ACCESS_TOKEN=your_access_token
TWITTER_OAUTH2_REFRESH_TOKEN=your_refresh_token

# Notion API
NOTION_TOKEN=your_notion_token
NOTION_DATABASE_ID=your_database_id

# Optional settings
SYNC_INTERVAL_MINUTES=10
LOG_LEVEL=INFO
```

### 5. Test the Setup

```bash
cd src
python -m twitter_notion_sync.sync_service --setup-only
```

If successful, you'll see "Setup completed successfully".

### 6. Run Initial Backfill (Optional)

To sync existing bookmarks:

```bash
python -m twitter_notion_sync.sync_service --backfill
```

Or limit to recent bookmarks:

```bash
python -m twitter_notion_sync.sync_service --backfill --backfill-limit 100
```

### 7. Run the Service

**Single sync:**
```bash
python -m twitter_notion_sync.sync_service --once
```

**Continuous service (foreground):**
```bash
python -m twitter_notion_sync.sync_service
```

**macOS background service:**
```bash
./scripts/setup_macos_service.sh
```

## Notion Database Schema

The service creates/uses these properties:

| Property | Type | Description |
|----------|------|-------------|
| Title | Title | First 100 chars of tweet, or "Tweet from @handle…" |
| Content | Rich Text | Full tweet text (or combined thread) |
| Author | Rich Text | "Display Name (@handle)" |
| URL | URL | Direct link to tweet |
| Bookmarked Date | Date | When you bookmarked it |
| Tweet Date | Date | When originally posted |
| Type | Select | "Regular Tweet", "Thread", or "Long-form" |
| Status | Select | "Unread" (default), "Read", or "Archived" |

## Usage

### Command Line Options

```
python -m twitter_notion_sync.sync_service [OPTIONS]

Options:
  -c, --config PATH        Path to .env file
  --backfill               Run one-time backfill of existing bookmarks
  --backfill-limit N       Max bookmarks for backfill
  --once                   Run single sync cycle and exit
  --setup-only             Only validate setup
  --status                 Show current sync status
```

### Managing the macOS Service

```bash
# Start
launchctl start com.sefermark.twitter-notion-sync

# Stop
launchctl stop com.sefermark.twitter-notion-sync

# View logs
tail -f ~/.twitter_notion_sync/sync.log

# Uninstall
./scripts/uninstall_macos_service.sh
```

### Check Sync Status

```bash
python -m twitter_notion_sync.sync_service --status
```

## File Locations

| File | Purpose |
|------|---------|
| `~/.twitter_notion_sync/state.json` | Tracks synced tweet IDs |
| `~/.twitter_notion_sync/sync.log` | Service logs |
| `~/Library/LaunchAgents/com.sefermark.twitter-notion-sync.plist` | macOS service config |

## Troubleshooting

### "Authentication failed" error

Your Twitter tokens may have expired. Re-run the OAuth setup:

```bash
python -m twitter_notion_sync.oauth_setup
```

### Rate limit errors

The service handles rate limits automatically, but if you're hitting them frequently:

1. Increase `SYNC_INTERVAL_MINUTES` in `.env`
2. Wait 15 minutes for the rate limit window to reset

### Notion "validation_error"

Make sure:
1. The database is shared with your integration
2. The database has a "Title" property (required)

### Service not starting

Check the logs:

```bash
tail -f ~/.twitter_notion_sync/launchd_stderr.log
tail -f ~/.twitter_notion_sync/sync.log
```

### Clearing sync state

To re-sync all bookmarks:

```bash
rm ~/.twitter_notion_sync/state.json
python -m twitter_notion_sync.sync_service --backfill
```

## Architecture

```
src/twitter_notion_sync/
├── __init__.py           # Package metadata
├── config.py             # Configuration management
├── twitter_client.py     # Twitter API client
├── notion_client.py      # Notion API client
├── state_manager.py      # Local state persistence
├── sync_service.py       # Main sync service
└── oauth_setup.py        # OAuth 2.0 setup helper
```

## API Rate Limits

**Twitter (Free Tier):**
- Bookmarks: 180 requests / 15 minutes
- User lookup: 75 requests / 15 minutes

**Notion:**
- 3 requests / second average
- Burst up to 50/second

The service automatically handles these limits with exponential backoff.

## Security Notes

- Never commit your `.env` file
- The state file contains tweet IDs but no sensitive data
- OAuth tokens should be kept secure
- Consider using a secrets manager for production

## License

MIT License - see LICENSE file for details.
