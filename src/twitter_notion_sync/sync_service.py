"""
Main sync service that coordinates Twitter bookmark fetching and Notion updates.

Runs as a background service with configurable polling interval.
"""

import logging
import signal
import sys
import time
from datetime import datetime
from typing import Optional

from .config import Config, load_config, ensure_directories
from .twitter_client import TwitterClient, Tweet
from .notion_client import NotionClient
from .state_manager import StateManager

logger = logging.getLogger(__name__)


class SyncService:
    """
    Main service that syncs Twitter bookmarks to Notion.

    Handles polling, deduplication, and error recovery.
    """

    def __init__(self, config: Config):
        """
        Initialize the sync service.

        Args:
            config: Application configuration
        """
        self.config = config
        self.twitter = TwitterClient(config.twitter)
        self.notion = NotionClient(config.notion)
        self.state = StateManager(config.sync.state_file_path)

        self._running = False
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Setup handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self._running = False

    def setup(self) -> bool:
        """
        Perform initial setup and validation.

        Returns:
            True if setup successful
        """
        logger.info("Running initial setup...")

        # Ensure directories exist
        ensure_directories(self.config)

        # Validate Notion database
        if not self.notion.validate_database():
            logger.info("Attempting to setup database schema...")
            if not self.notion.setup_database():
                logger.error("Failed to setup Notion database")
                return False

        # Test Twitter authentication
        try:
            user_id = self.twitter.get_user_id()
            logger.info(f"Twitter authentication successful (user ID: {user_id})")
        except Exception as e:
            logger.error(f"Twitter authentication failed: {e}")
            return False

        logger.info("Setup completed successfully")
        return True

    def sync_bookmark(self, tweet: Tweet) -> bool:
        """
        Sync a single bookmark to Notion.

        Args:
            tweet: Tweet to sync

        Returns:
            True if sync successful
        """
        # Check if already synced
        if self.state.is_synced(tweet.id):
            logger.debug(f"Tweet {tweet.id} already synced, skipping")
            return True

        # Add to Notion
        page_id = self.notion.add_tweet(tweet)

        if page_id:
            self.state.mark_synced(tweet.id)
            return True
        else:
            logger.warning(f"Failed to sync tweet {tweet.id}")
            return False

    def run_sync_cycle(self) -> dict:
        """
        Run a single sync cycle.

        Returns:
            Statistics about the sync cycle
        """
        stats = {
            "started_at": datetime.utcnow().isoformat(),
            "tweets_fetched": 0,
            "tweets_synced": 0,
            "tweets_skipped": 0,
            "errors": 0,
        }

        logger.info("Starting sync cycle...")

        try:
            # Fetch bookmarks
            for tweet in self.twitter.fetch_all_bookmarks():
                stats["tweets_fetched"] += 1

                # Check if already synced (avoid unnecessary API calls)
                if self.state.is_synced(tweet.id):
                    stats["tweets_skipped"] += 1
                    continue

                # Sync to Notion
                if self.sync_bookmark(tweet):
                    stats["tweets_synced"] += 1
                else:
                    stats["errors"] += 1

                # Small delay to be nice to APIs
                time.sleep(0.5)

        except Exception as e:
            logger.error(f"Error during sync cycle: {e}")
            stats["error_message"] = str(e)

        # Update last sync time
        self.state.update_last_sync_time()

        stats["completed_at"] = datetime.utcnow().isoformat()
        logger.info(
            f"Sync cycle complete: {stats['tweets_synced']} synced, "
            f"{stats['tweets_skipped']} skipped, {stats['errors']} errors"
        )

        return stats

    def run_backfill(self, limit: Optional[int] = None) -> dict:
        """
        Run a backfill to sync all existing bookmarks.

        This is useful for initial setup or after clearing state.

        Args:
            limit: Maximum number of bookmarks to sync

        Returns:
            Statistics about the backfill
        """
        logger.info(f"Starting backfill (limit: {limit or 'none'})...")

        stats = {
            "started_at": datetime.utcnow().isoformat(),
            "tweets_processed": 0,
            "tweets_synced": 0,
            "tweets_skipped": 0,
            "errors": 0,
        }

        try:
            for tweet in self.twitter.fetch_all_bookmarks(limit=limit):
                stats["tweets_processed"] += 1

                if self.state.is_synced(tweet.id):
                    stats["tweets_skipped"] += 1
                    continue

                if self.sync_bookmark(tweet):
                    stats["tweets_synced"] += 1
                else:
                    stats["errors"] += 1

                # Progress logging
                if stats["tweets_processed"] % 10 == 0:
                    logger.info(f"Backfill progress: {stats['tweets_processed']} processed")

                # Rate limit friendly delay
                time.sleep(0.5)

        except Exception as e:
            logger.error(f"Error during backfill: {e}")
            stats["error_message"] = str(e)

        stats["completed_at"] = datetime.utcnow().isoformat()
        logger.info(
            f"Backfill complete: {stats['tweets_synced']} synced, "
            f"{stats['tweets_skipped']} already existed"
        )

        return stats

    def run(self) -> None:
        """
        Run the sync service continuously.

        Polls for new bookmarks at the configured interval.
        """
        self._running = True
        interval_seconds = self.config.sync.interval_minutes * 60

        logger.info(
            f"Starting sync service (polling every {self.config.sync.interval_minutes} minutes)"
        )

        while self._running:
            try:
                self.run_sync_cycle()
            except Exception as e:
                logger.error(f"Unexpected error in sync cycle: {e}", exc_info=True)

            if not self._running:
                break

            # Wait for next cycle
            logger.info(f"Waiting {self.config.sync.interval_minutes} minutes until next sync...")

            # Sleep in smaller chunks to allow graceful shutdown
            for _ in range(interval_seconds):
                if not self._running:
                    break
                time.sleep(1)

        logger.info("Sync service stopped")

    def get_status(self) -> dict:
        """
        Get current service status.

        Returns:
            Status dictionary
        """
        return {
            "running": self._running,
            "sync_stats": self.state.get_stats(),
            "config": {
                "interval_minutes": self.config.sync.interval_minutes,
                "state_file": str(self.config.sync.state_file_path),
                "log_file": str(self.config.sync.log_file_path),
            },
        }


def setup_logging(config: Config) -> None:
    """
    Configure logging for the service.

    Args:
        config: Application configuration
    """
    # Ensure log directory exists
    config.sync.log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=getattr(logging, config.sync.log_level),
        format=log_format,
        handlers=[
            logging.FileHandler(config.sync.log_file_path),
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def main():
    """Main entry point for the sync service."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Twitter Bookmarks to Notion Sync Service"
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to .env configuration file",
        default=None,
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Run a one-time backfill of existing bookmarks",
    )
    parser.add_argument(
        "--backfill-limit",
        type=int,
        help="Maximum number of bookmarks to sync during backfill",
        default=None,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single sync cycle and exit",
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Only run setup/validation and exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current sync status and exit",
    )

    args = parser.parse_args()

    # Load configuration
    try:
        config = load_config(args.config)
    except ValueError as e:
        print(f"Configuration error: {e}")
        print("Please ensure all required environment variables are set.")
        print("See .env.example for the required variables.")
        sys.exit(1)

    # Setup logging
    setup_logging(config)

    # Create service
    service = SyncService(config)

    # Handle different modes
    if args.status:
        status = service.get_status()
        print("Sync Service Status:")
        print(f"  State file: {status['config']['state_file']}")
        print(f"  Log file: {status['config']['log_file']}")
        print(f"  Poll interval: {status['config']['interval_minutes']} minutes")
        print(f"  Total synced: {status['sync_stats']['total_synced']}")
        print(f"  Unique tweets: {status['sync_stats']['unique_tweets']}")
        print(f"  Last sync: {status['sync_stats']['last_sync']}")
        sys.exit(0)

    # Run setup
    if not service.setup():
        logger.error("Setup failed. Please check your configuration.")
        sys.exit(1)

    if args.setup_only:
        logger.info("Setup completed successfully")
        sys.exit(0)

    # Run backfill if requested
    if args.backfill:
        stats = service.run_backfill(limit=args.backfill_limit)
        if "error_message" in stats:
            sys.exit(1)
        sys.exit(0)

    # Run single sync or continuous service
    if args.once:
        stats = service.run_sync_cycle()
        if "error_message" in stats:
            sys.exit(1)
    else:
        service.run()


if __name__ == "__main__":
    main()
