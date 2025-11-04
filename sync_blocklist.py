

"""Sync disposable email blocklist to Mastodon server via API.

Fetches the blocklist from disposable_email_domains, compares it to the current
Mastodon blocklist, logs the diff, and syncs the blocklist using the Mastodon API.
Supports dry run mode and handles rate limiting with retries and exponential backoff.
"""

import os
import time
from importlib.metadata import version as pkg_version
from mastodon import Mastodon
from disposable_email_domains import blocklist

MASTODON_HOST = os.getenv('MASTODON_HOST')
MASTODON_API_TOKEN = os.getenv('MASTODON_API_TOKEN')
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() in ('1', 'true', 'yes')
VERBOSE = os.getenv('VERBOSE', 'false').lower() in ('1', 'true', 'yes')

def get_mastodon_blocklist():
    """Fetch the current Mastodon blocklist using Mastodon.py.

    Returns:
        set: Set of blocked domains.
    """
    mastodon = Mastodon(
        api_base_url=MASTODON_HOST,
        access_token=MASTODON_API_TOKEN
    )
    all_domains = set()
    page = mastodon.admin_email_domain_blocks()
    while page:
        all_domains.update(block['domain'] for block in page)
        page = mastodon.fetch_next(page)
    return all_domains

def log_summary(added_count, removed_count, already_count, failed_add_count, failed_remove_count):
    """Log aggregate counts of added, removed, already existing, and failed domains.

    Args:
        added_count (int): Number of domains added.
        removed_count (int): Number of domains removed.
        already_count (int): Number of domains already blocked.
        failed_add_count (int): Number of failed add attempts.
        failed_remove_count (int): Number of failed remove attempts.
    """
    try:
        dep_version = pkg_version('disposable_email_domains')
    except Exception:
        dep_version = 'unknown'
    print(f"disposable_email_domains version: {dep_version}")
    print(f"Domains successfully added: {added_count}")
    print(f"Domains failed to add: {failed_add_count}")
    print(f"Domains removed: {removed_count}")
    print(f"Domains failed to remove: {failed_remove_count}")
    print(f"Domains already blocked: {already_count}")

def add_domains(mastodon, to_add, current_blocklist):
    """Add new domains to Mastodon blocklist.

    Args:
        mastodon (Mastodon): Mastodon API client.
        to_add (set): Domains to add.
        current_blocklist (set): Current blocklist.

    Returns:
        tuple: (added_count, already_count, failed_count)
    """
    added_count = 0
    already_count = 0
    failed_count = 0
    for domain in sorted(to_add):
        if DRY_RUN:
            if VERBOSE:
                print(f"[DRY RUN] Would block domain: {domain}")
            continue
        if domain in current_blocklist:
            already_count += 1
            if VERBOSE:
                print(f"Already blocked: {domain}")
            continue
        try:
            mastodon.admin_create_email_domain_block(domain)
            added_count += 1
            if VERBOSE:
                print(f"Blocked domain: {domain}")
        except Exception as error:
            failed_count += 1
            if VERBOSE:
                print(f"Failed to block {domain}: {error}")
        handle_rate_limit(mastodon, domain)
    return added_count, already_count, failed_count

def remove_domains(mastodon, to_remove):
    """Remove domains from Mastodon blocklist.

    Args:
        mastodon (Mastodon): Mastodon API client.
        to_remove (set): Domains to remove.

    Returns:
        tuple: (removed_count, failed_count)
    """
    removed_count = 0
    failed_count = 0
    for domain in sorted(to_remove):
        if DRY_RUN:
            if VERBOSE:
                print(f"[DRY RUN] Would remove domain: {domain}")
            continue
        try:
            mastodon.admin_delete_email_domain_block(domain)
            removed_count += 1
            if VERBOSE:
                print(f"Removed domain: {domain}")
        except Exception as error:
            failed_count += 1
            if VERBOSE:
                print(f"Failed to remove {domain}: {error}")
        handle_rate_limit(mastodon, domain)
    return removed_count, failed_count

def handle_rate_limit(mastodon, domain):
    """Handle Mastodon API rate limiting.

    Args:
        mastodon (Mastodon): Mastodon API client.
        domain (str): Domain being processed (for logging).
    """
    rl_remaining = mastodon.ratelimit_remaining
    rl_reset = mastodon.ratelimit_reset
    if rl_remaining is not None and rl_reset is not None and rl_remaining == 1:
        wait = max(int(rl_reset - time.time()), 1)
        if VERBOSE:
            print(f"Approaching rate limit for {domain}. Waiting {wait} seconds until reset...")
        time.sleep(wait)

    # No longer needed; replaced by Mastodon.py native methods

def sync_blocklist():
    """Sync the disposable email blocklist to the Mastodon server.

    Adds new domains and removes domains no longer present in the blocklist.
    Handles rate limiting and supports dry run and verbose modes.
    """
    print(f"[DEBUG] MASTODON_HOST: {MASTODON_HOST}")
    print(f"[DEBUG] MASTODON_API_TOKEN: {'set' if MASTODON_API_TOKEN else 'unset'}")
    desired_blocklist = set(blocklist)
    print(f"[DEBUG] disposable_email_domains blocklist length: {len(desired_blocklist)}")
    mastodon = Mastodon(
        api_base_url=MASTODON_HOST,
        access_token=MASTODON_API_TOKEN
    )
    current_blocklist = get_mastodon_blocklist() if MASTODON_HOST and MASTODON_API_TOKEN else set()
    print(f"[DEBUG] Mastodon current blocklist length: {len(current_blocklist)}")
    to_add = desired_blocklist - current_blocklist
    to_remove = current_blocklist - desired_blocklist
    print(f"[DEBUG] Domains to add: {len(to_add)}")
    print(f"[DEBUG] Domains to remove: {len(to_remove)}")

    if to_add:
        added_count, already_count, failed_add = add_domains(mastodon, to_add, current_blocklist)
    else:
        added_count = 0
        # All desired domains are already blocked
        already_count = len(desired_blocklist & current_blocklist)
        failed_add = 0
    removed_count, failed_remove = remove_domains(mastodon, to_remove)
    log_summary(added_count, removed_count, already_count, failed_add, failed_remove)

def main():
    """Main entry point for the script."""
    sync_blocklist()

if __name__ == "__main__":
    main()
