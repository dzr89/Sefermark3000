#!/bin/bash
#
# Uninstall script for Twitter-Notion Sync macOS service
#
# Usage: ./uninstall_macos_service.sh
#

set -e

PLIST_NAME="com.sefermark.twitter-notion-sync.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "=========================================="
echo "Twitter-Notion Sync - Uninstall Service"
echo "=========================================="
echo

# Check if service is installed
if [[ ! -f "$PLIST_PATH" ]]; then
    echo "Service not installed (plist not found)."
    exit 0
fi

# Stop and unload service
echo "Stopping service..."
launchctl stop com.sefermark.twitter-notion-sync 2>/dev/null || true

echo "Unloading service..."
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# Remove plist
echo "Removing plist file..."
rm -f "$PLIST_PATH"

echo
echo "Service uninstalled successfully!"
echo
echo "Note: State files are preserved in ~/.twitter_notion_sync/"
echo "To completely remove all data, run:"
echo "  rm -rf ~/.twitter_notion_sync/"
