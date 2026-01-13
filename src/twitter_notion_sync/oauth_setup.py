"""
OAuth 2.0 setup helper for Twitter API authentication.

This script helps users complete the OAuth 2.0 PKCE flow
to obtain the access and refresh tokens needed for bookmark access.
"""

import base64
import hashlib
import secrets
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import os
import json

# Load environment for client credentials
from dotenv import load_dotenv


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""

    def do_GET(self):
        """Handle the OAuth callback."""
        parsed = urlparse(self.path)

        if parsed.path == "/callback":
            params = parse_qs(parsed.query)

            if "code" in params:
                self.server.auth_code = params["code"][0]
                self.server.auth_state = params.get("state", [None])[0]

                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"""
                    <html>
                    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                        <h1>Authorization Successful!</h1>
                        <p>You can close this window and return to the terminal.</p>
                    </body>
                    </html>
                """)
            else:
                error = params.get("error", ["Unknown error"])[0]
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(f"""
                    <html>
                    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                        <h1>Authorization Failed</h1>
                        <p>Error: {error}</p>
                    </body>
                    </html>
                """.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def generate_pkce_pair():
    """Generate PKCE code verifier and challenge."""
    # Generate code verifier
    code_verifier = secrets.token_urlsafe(32)

    # Generate code challenge (SHA256 hash, base64 encoded)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")

    return code_verifier, code_challenge


def run_oauth_flow():
    """Run the interactive OAuth 2.0 setup flow."""
    print("=" * 60)
    print("Twitter OAuth 2.0 Setup")
    print("=" * 60)
    print()

    # Load existing .env if present
    load_dotenv()

    # Get client credentials
    client_id = os.getenv("TWITTER_OAUTH2_CLIENT_ID")
    client_secret = os.getenv("TWITTER_OAUTH2_CLIENT_SECRET")

    if not client_id:
        print("Enter your Twitter OAuth 2.0 Client ID:")
        print("(Get this from https://developer.twitter.com/)")
        client_id = input("> ").strip()

    if not client_secret:
        print("\nEnter your Twitter OAuth 2.0 Client Secret:")
        client_secret = input("> ").strip()

    print()

    # Set up redirect URI and local server
    redirect_port = 3000
    redirect_uri = f"http://localhost:{redirect_port}/callback"

    print(f"Using redirect URI: {redirect_uri}")
    print("Make sure this is added to your Twitter app's callback URLs!")
    print()

    # Generate PKCE parameters
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)

    # Build authorization URL
    scopes = ["tweet.read", "users.read", "bookmark.read", "offline.access"]
    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    from urllib.parse import urlencode
    auth_url = f"https://twitter.com/i/oauth2/authorize?{urlencode(auth_params)}"

    print("Opening browser for authorization...")
    print(f"If browser doesn't open, visit this URL:\n{auth_url}")
    print()

    # Open browser
    webbrowser.open(auth_url)

    # Start local server to receive callback
    print(f"Waiting for callback on port {redirect_port}...")

    server = HTTPServer(("localhost", redirect_port), OAuthCallbackHandler)
    server.auth_code = None
    server.auth_state = None
    server.timeout = 300  # 5 minute timeout

    # Wait for callback
    while server.auth_code is None:
        server.handle_request()

    if server.auth_state != state:
        print("Error: State mismatch. Possible CSRF attack.")
        return

    print("\nAuthorization code received!")
    print("Exchanging for access token...")

    # Exchange code for token
    import requests

    token_url = "https://api.twitter.com/2/oauth2/token"

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    token_data = {
        "grant_type": "authorization_code",
        "code": server.auth_code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    response = requests.post(
        token_url,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=token_data,
    )

    if response.status_code != 200:
        print(f"Error getting token: {response.text}")
        return

    token_response = response.json()

    print()
    print("=" * 60)
    print("SUCCESS! Here are your tokens:")
    print("=" * 60)
    print()
    print("Add these to your .env file:")
    print()
    print(f"TWITTER_OAUTH2_CLIENT_ID={client_id}")
    print(f"TWITTER_OAUTH2_CLIENT_SECRET={client_secret}")
    print(f"TWITTER_OAUTH2_ACCESS_TOKEN={token_response['access_token']}")
    print(f"TWITTER_OAUTH2_REFRESH_TOKEN={token_response.get('refresh_token', 'N/A')}")
    print()

    # Offer to save to .env
    print("Would you like to save these to .env? (y/n)")
    save = input("> ").strip().lower()

    if save == "y":
        env_content = f"""# Twitter OAuth 2.0 Credentials
TWITTER_OAUTH2_CLIENT_ID={client_id}
TWITTER_OAUTH2_CLIENT_SECRET={client_secret}
TWITTER_OAUTH2_ACCESS_TOKEN={token_response['access_token']}
TWITTER_OAUTH2_REFRESH_TOKEN={token_response.get('refresh_token', '')}

# Notion API Credentials (fill these in)
NOTION_TOKEN=your_notion_token_here
NOTION_DATABASE_ID=your_database_id_here

# Sync Configuration
SYNC_INTERVAL_MINUTES=10
LOG_LEVEL=INFO
STATE_FILE_PATH=~/.twitter_notion_sync/state.json
LOG_FILE_PATH=~/.twitter_notion_sync/sync.log
"""
        with open(".env", "w") as f:
            f.write(env_content)
        print("\nSaved to .env")
        print("Don't forget to add your Notion credentials!")

    print()
    print("Setup complete! You can now run the sync service.")


if __name__ == "__main__":
    run_oauth_flow()
