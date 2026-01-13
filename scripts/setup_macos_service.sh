#!/bin/bash
#
# Setup script for Twitter-Notion Sync as a macOS launchd service
#
# Usage: ./setup_macos_service.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.sefermark.twitter-notion-sync.plist"
PLIST_SOURCE="$PROJECT_DIR/$PLIST_NAME"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "=========================================="
echo "Twitter-Notion Sync - macOS Service Setup"
echo "=========================================="
echo

# Check if we're on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Error: This script is for macOS only."
    exit 1
fi

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 not found. Please install Python 3 first."
    exit 1
fi

PYTHON_PATH=$(which python3)
echo "Found Python at: $PYTHON_PATH"

# Check for virtualenv
if [[ -d "$PROJECT_DIR/venv" ]]; then
    PYTHON_PATH="$PROJECT_DIR/venv/bin/python3"
    echo "Using virtualenv Python: $PYTHON_PATH"
fi

# Get current user
CURRENT_USER=$(whoami)
echo "Current user: $CURRENT_USER"
echo

# Create state directory
STATE_DIR="$HOME/.twitter_notion_sync"
mkdir -p "$STATE_DIR"
echo "Created state directory: $STATE_DIR"

# Check for .env file
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    if [[ -f "$PROJECT_DIR/.env.example" ]]; then
        echo
        echo "Warning: .env file not found!"
        echo "Please copy .env.example to .env and fill in your credentials:"
        echo "  cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env"
        echo
    fi
fi

# Create customized plist
echo "Creating launchd plist..."

# Read template and substitute values
sed -e "s|/usr/local/bin/python3|$PYTHON_PATH|g" \
    -e "s|YOUR_USERNAME|$CURRENT_USER|g" \
    -e "s|/Users/$CURRENT_USER/Sefermark3000|$PROJECT_DIR|g" \
    "$PLIST_SOURCE" > "$PLIST_DEST"

echo "Created: $PLIST_DEST"

# Unload existing service if present
if launchctl list | grep -q "com.sefermark.twitter-notion-sync"; then
    echo "Unloading existing service..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Load the service
echo "Loading service..."
launchctl load "$PLIST_DEST"

# Check status
echo
echo "Service status:"
if launchctl list | grep -q "com.sefermark.twitter-notion-sync"; then
    launchctl list | grep "com.sefermark.twitter-notion-sync"
    echo
    echo "Service installed and running!"
else
    echo "Service loaded but may not be running yet."
fi

echo
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo
echo "Useful commands:"
echo "  Start:   launchctl start com.sefermark.twitter-notion-sync"
echo "  Stop:    launchctl stop com.sefermark.twitter-notion-sync"
echo "  Restart: launchctl stop com.sefermark.twitter-notion-sync && launchctl start com.sefermark.twitter-notion-sync"
echo "  Unload:  launchctl unload $PLIST_DEST"
echo "  Logs:    tail -f $STATE_DIR/sync.log"
echo
echo "The service will start automatically on login."
