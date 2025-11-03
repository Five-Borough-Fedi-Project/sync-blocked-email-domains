#!/usr/bin/env python3
"""
Sync blocked email domains from disposable-email-domains repository to Mastodon.

This script fetches the list of disposable email domains from the
disposable-email-domains GitHub repository and syncs them to a Mastodon
instance using the Admin API.
"""

import os
import sys
import logging
from typing import Set
import requests
from dotenv import load_dotenv


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MastodonEmailBlockSync:
    """Sync disposable email domains to Mastodon."""

    def __init__(
        self, mastodon_host: str, api_token: str, disposable_domains_url: str = None
    ):
        """
        Initialize the sync client.

        Args:
            mastodon_host: Mastodon server host (e.g., https://mastodon.social)
            api_token: Mastodon API token with admin:write:email_domain_blocks scope
            disposable_domains_url: URL to fetch disposable domains list
        """
        self.mastodon_host = mastodon_host.rstrip("/")
        self.api_token = api_token
        self.disposable_domains_url = disposable_domains_url or (
            "https://raw.githubusercontent.com/disposable-email-domains/"
            "disposable-email-domains/master/disposable_email_blocklist.conf"
        )
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def fetch_disposable_domains(self) -> Set[str]:
        """
        Fetch the list of disposable email domains.

        Returns:
            Set of domain names
        """
        logger.info(f"Fetching disposable domains from {self.disposable_domains_url}")
        try:
            response = requests.get(self.disposable_domains_url, timeout=30)
            response.raise_for_status()

            # Parse domains from file (one per line, ignore comments/empty lines)
            domains = set()
            for line in response.text.splitlines():
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith("#"):
                    domains.add(line.lower())

            logger.info(f"Fetched {len(domains)} disposable domains")
            return domains
        except requests.RequestException as e:
            logger.error(f"Failed to fetch disposable domains: {e}")
            raise

    def get_existing_blocks(self) -> Set[str]:
        """
        Get existing email domain blocks from Mastodon.

        Returns:
            Set of blocked domain names
        """
        logger.info("Fetching existing email domain blocks from Mastodon")
        blocked_domains = set()
        url = f"{self.mastodon_host}/api/v1/admin/email_domain_blocks"

        try:
            # Mastodon API uses pagination
            while url:
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()

                blocks = response.json()
                for block in blocks:
                    blocked_domains.add(block["domain"].lower())

                # Check for next page
                link_header = response.headers.get("Link", "")
                url = self._parse_next_link(link_header)

            logger.info(f"Found {len(blocked_domains)} existing blocks")
            return blocked_domains
        except requests.RequestException as e:
            logger.error(f"Failed to fetch existing blocks: {e}")
            raise

    def _parse_next_link(self, link_header: str) -> str:
        """
        Parse the Link header to get the next page URL.

        Args:
            link_header: The Link header from the response

        Returns:
            The next page URL or empty string if no next page
        """
        if not link_header:
            return ""

        links = link_header.split(",")
        for link in links:
            parts = link.split(";")
            if len(parts) == 2:
                url = parts[0].strip()[1:-1]  # Remove < and >
                rel = parts[1].strip()
                if 'rel="next"' in rel:
                    return url
        return ""

    def block_domain(self, domain: str) -> bool:
        """
        Block a single email domain on Mastodon.

        Args:
            domain: The domain to block

        Returns:
            True if successful, False otherwise
        """
        url = f"{self.mastodon_host}/api/v1/admin/email_domain_blocks"
        data = {"domain": domain}

        try:
            response = requests.post(url, headers=self.headers, json=data, timeout=30)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to block domain {domain}: {e}")
            return False

    def sync_domains(self, dry_run: bool = False) -> dict:
        """
        Sync disposable email domains to Mastodon.

        Args:
            dry_run: If True, only show what would be done without making changes

        Returns:
            Dictionary with sync statistics
        """
        logger.info("Starting email domain block sync")

        # Fetch disposable domains and existing blocks
        disposable_domains = self.fetch_disposable_domains()
        existing_blocks = self.get_existing_blocks()

        # Calculate domains to add
        domains_to_add = disposable_domains - existing_blocks

        stats = {
            "total_disposable": len(disposable_domains),
            "existing_blocks": len(existing_blocks),
            "to_add": len(domains_to_add),
            "added": 0,
            "failed": 0,
        }

        if not domains_to_add:
            logger.info("All disposable domains are already blocked")
            return stats

        logger.info(f"Found {len(domains_to_add)} new domains to block")

        if dry_run:
            logger.info("DRY RUN: Would block the following domains:")
            for domain in sorted(domains_to_add):
                logger.info(f"  - {domain}")
            return stats

        # Add new blocks
        for domain in sorted(domains_to_add):
            if self.block_domain(domain):
                stats["added"] += 1
                logger.info(f"Blocked: {domain}")
            else:
                stats["failed"] += 1

        logger.info(f"Sync complete: {stats['added']} added, {stats['failed']} failed")
        return stats


def main():
    """Main entry point for the script."""
    # Load environment variables
    load_dotenv()

    # Get configuration from environment
    mastodon_host = os.getenv("MASTODON_HOST")
    api_token = os.getenv("MASTODON_API_TOKEN")
    disposable_domains_url = os.getenv("DISPOSABLE_DOMAINS_URL")
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    # Validate required configuration
    if not mastodon_host:
        logger.error("MASTODON_HOST environment variable is required")
        sys.exit(1)

    if not api_token:
        logger.error("MASTODON_API_TOKEN environment variable is required")
        sys.exit(1)

    # Initialize sync client
    try:
        sync_client = MastodonEmailBlockSync(
            mastodon_host=mastodon_host,
            api_token=api_token,
            disposable_domains_url=disposable_domains_url,
        )

        # Perform sync
        stats = sync_client.sync_domains(dry_run=dry_run)

        logger.info("Sync statistics:")
        logger.info(f"  Total disposable domains: {stats['total_disposable']}")
        logger.info(f"  Existing blocks: {stats['existing_blocks']}")
        logger.info(f"  Domains to add: {stats['to_add']}")
        logger.info(f"  Successfully added: {stats['added']}")
        logger.info(f"  Failed: {stats['failed']}")

        if stats["failed"] > 0:
            sys.exit(1)

    except Exception as e:
        logger.exception(f"Sync failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
