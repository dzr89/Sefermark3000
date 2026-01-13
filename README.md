# Sefermark3000

Save Twitter/X content to Notion by texting a link to your phone number.

## How It Works

```
1. Find a tweet or article on Twitter/X
2. Share it → Copy link
3. Text the link to your Twilio number
4. Content is fetched (including full articles/essays)
5. Entry is created in your Notion database
6. You get a confirmation SMS back
```

## Features

- **Full article extraction** - Long-form Twitter articles are fully extracted, not just previews
- **Smart formatting** - Headings, paragraphs, lists, and quotes are preserved in Notion
- **Categories** - Add a category by texting `tech https://x.com/...` or `https://x.com/... tech`
- **No Twitter API needed** - Uses free FXTwitter API (no $200/month subscription required)
- **Works from mobile** - Just text a link from your phone

## SMS Formats

| Format | Example |
|--------|---------|
| Just URL | `https://x.com/user/status/123` |
| URL + category | `https://x.com/user/status/123 tech` |
| Category + URL | `tech https://x.com/user/status/123` |

## Setup

### 1. Clone and Install

```bash
git clone https://github.com/dzr89/Sefermark3000.git
cd Sefermark3000
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Create Notion Integration

1. Go to https://www.notion.so/my-integrations
2. Create a new integration
3. Copy the Integration Token

### 3. Create Notion Database

1. Create a new database in Notion
2. Share it with your integration (... menu → Connections → Add your integration)
3. Copy the database ID from the URL

The service will automatically create these properties:
- **Name** (title) - Tweet/article title
- **Author** (text) - Author name and handle
- **URL** (url) - Link to original tweet
- **Bookmarked Date** (date) - When you saved it
- **Type** (select) - Regular Tweet, Long-form, Thread
- **Status** (select) - Unread, Read, Archived
- **Category** (select) - Your custom categories

### 4. Set Up Twilio

1. Create account at https://www.twilio.com/try-twilio
2. Buy a phone number (~$1.15/month)
3. Copy your Account SID and Auth Token

### 5. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
NOTION_TOKEN=your_notion_token
NOTION_DATABASE_ID=your_database_id
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_PHONE_NUMBER=+1234567890
```

### 6. Run the Server

```bash
source venv/bin/activate
cd src
python -m twitter_notion_sync.sms_webhook
```

### 7. Expose to Internet

For Twilio to reach your server, you need a public URL.

**Development (ngrok):**
```bash
ngrok http 5000
```

**Production (Cloudflare Tunnel):**
```bash
cloudflared tunnel run --url http://localhost:5000 sefermark
```

### 8. Configure Twilio Webhook

1. Go to Twilio Console → Phone Numbers → Your number
2. Set "A Message Comes In" webhook to: `https://your-url/sms`
3. Method: POST

## Production Deployment

For 24/7 operation, you have several options:

### Option A: Railway (Recommended)

1. **Create Railway account** at https://railway.app

2. **Create new project** → "Deploy from GitHub repo" → Select your fork

3. **Set environment variables** in Railway → Your service → Variables:

   | Variable | Value |
   |----------|-------|
   | `NOTION_TOKEN` | `ntn_xxxxx...` (just the token, not `NOTION_TOKEN=ntn_xxx`) |
   | `NOTION_DATABASE_ID` | `abc123...` (32-char ID from your Notion database URL) |
   | `TWILIO_AUTH_TOKEN` | Your Twilio auth token |

   > **Important:** Only paste the value itself, not `VAR_NAME=value`. Railway adds the variable name separately.

4. **Deploy** - Railway auto-deploys on every push. Your URL will be:
   ```
   https://your-service-name.up.railway.app
   ```

5. **Configure Twilio webhook** to point to your Railway URL:
   ```
   https://your-service-name.up.railway.app/sms
   ```

6. **Verify** by hitting the health endpoint:
   ```
   https://your-service-name.up.railway.app/health
   ```
   Should return `{"status":"ok"}`

### Option B: Self-hosted with systemd

Create `/etc/systemd/system/sefermark.service`:

```ini
[Unit]
Description=Sefermark3000 SMS Webhook
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/Sefermark3000
Environment=PYTHONPATH=/path/to/Sefermark3000/src
ExecStart=/path/to/Sefermark3000/venv/bin/python -m twitter_notion_sync.sms_webhook
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable sefermark
sudo systemctl start sefermark
```

### Option C: macOS with launchd

```bash
./scripts/setup_macos_service.sh
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Mobile    │────▶│   Twilio    │────▶│   Server    │
│  (SMS link) │     │  (webhook)  │     │  (Flask)    │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    ┌─────────────┐     ┌──────▼──────┐
                    │   Notion    │◀────│  FXTwitter  │
                    │  (database) │     │    (API)    │
                    └─────────────┘     └─────────────┘
```

## Files

```
src/twitter_notion_sync/
├── sms_webhook.py      # Main SMS webhook service
├── config.py           # Configuration management
├── notion_client.py    # Notion API client
└── ...                 # Legacy Twitter API code (unused)
```

## API Used

This project uses the [FXTwitter API](https://github.com/FixTweet/FxTwitter) which:
- Requires no authentication
- Returns full article content
- Has no rate limits for normal use
- Is completely free

## License

MIT License
