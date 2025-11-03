
"""Sync disposable email blocklist to Mastodon server via API.

Fetches the blocklist from disposable_email_domains, compares it to the current
Mastodon blocklist, logs the diff, and syncs the blocklist using the Mastodon API.
Supports dry run mode and handles rate limiting with retries and exponential backoff.
"""

import os
import time
import requests
from disposable_email_domains import blocklist
from importlib.metadata import version as pkg_version
from mastodon import Mastodon

MASTODON_HOST = os.getenv('MASTODON_HOST')
MASTODON_API_TOKEN = os.getenv('MASTODON_API_TOKEN')
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() in ('1', 'true', 'yes')
VERBOSE = os.getenv('VERBOSE', 'false').lower() in ('1', 'true', 'yes')
MAX_RETRIES = 5

def get_mastodon_blocklist():
    """Fetch the current Mastodon blocklist using Mastodon.py.

    Returns:
        set: Set of blocked domains.
    """
    mastodon = Mastodon(
        api_base_url=MASTODON_HOST,
        access_token=MASTODON_API_TOKEN
    )
    blocks = mastodon.admin_email_domain_blocks()
    return {block['domain'] for block in blocks}

def log_summary(added_count, removed_count, already_count, failed_count):
    """Log aggregate counts of added, removed, already existing, and failed domains."""
    try:
        dep_version = pkg_version('disposable_email_domains')
    except Exception:
        dep_version = 'unknown'
    print(f"disposable_email_domains version: {dep_version}")
    print(f"Domains successfully added: {added_count}")
    print(f"Domains failed to add: {failed_count}")
    print(f"Domains to be removed: {removed_count}")
    print(f"Domains already blocked: {already_count}")

def sync_blocklist():
    """Sync the disposable email blocklist to the Mastodon server."""
    desired_blocklist = set(blocklist)
    current_blocklist = get_mastodon_blocklist() if MASTODON_HOST and MASTODON_API_TOKEN else set()
    api_url = f"{MASTODON_HOST.rstrip('/')}/api/v1/admin/email_domain_blocks"
    headers = {
        "Authorization": f"Bearer {MASTODON_API_TOKEN}",
        "Content-Type": "application/json"
    }
    added_count = 0
    removed_count = 0
    already_count = 0
    failed_count = 0
    # Calculate sets for summary
    to_add = desired_blocklist - current_blocklist
    to_remove = current_blocklist - desired_blocklist
    already = desired_blocklist & current_blocklist
    # Add new domains
    for domain in sorted(desired_blocklist):
        if DRY_RUN:
            if VERBOSE:
                print(f"[DRY RUN] Would block domain: {domain}")
            continue
        if domain in current_blocklist:
            already_count += 1
            if VERBOSE:
                print(f"Already blocked: {domain}")
            continue
        payload = {"domain": domain}
        result = post_with_retry(api_url, payload, headers, domain)
        if result:
            added_count += 1
            if VERBOSE:
                print(f"Blocked domain: {domain}")
        else:
            failed_count += 1
            if VERBOSE:
                print(f"Failed to block {domain}")

    # Remove domains not in blocklist
    removed_count = 0
    for domain in sorted(to_remove):
        if DRY_RUN:
            if VERBOSE:
                print(f"[DRY RUN] Would remove domain: {domain}")
            continue
        remove_url = f"{api_url}/{domain}"
        response = requests.delete(remove_url, headers=headers)
        if response.status_code == 200:
            removed_count += 1
            if VERBOSE:
                print(f"Removed domain: {domain}")
        else:
            failed_count += 1
            if VERBOSE:
                print(f"Failed to remove {domain}: {response.status_code} {response.text}")
    log_summary(added_count, removed_count, already_count, failed_count)

def post_with_retry(url, payload, headers, domain, max_retries=MAX_RETRIES):
    """POST to the Mastodon API with retry and exponential backoff for rate limiting.

    Args:
        url (str): API endpoint URL.
        payload (dict): JSON payload.
        headers (dict): HTTP headers.
        domain (str): Domain being blocked.
        max_retries (int): Maximum number of retries.

    Returns:
        bool: True if successful or already blocked, False otherwise.
    """
    retries = 0
    while retries <= max_retries:
        response = requests.post(url, json=payload, headers=headers)
        # Check Mastodon rate limit headers
        rate_limit = response.headers.get('X-RateLimit-Limit')
        rate_remaining = response.headers.get('X-RateLimit-Remaining')
        rate_reset = response.headers.get('X-RateLimit-Reset')
        if rate_limit and rate_remaining and rate_reset:
            try:
                rate_limit = int(rate_limit)
                rate_remaining = int(rate_remaining)
                # Parse rate_reset as either int (epoch) or ISO8601 string
                if rate_reset.isdigit():
                    reset_epoch = int(rate_reset)
                else:
                    from datetime import datetime
                    try:
                        reset_epoch = int(datetime.fromisoformat(rate_reset.rstrip('Z')).timestamp())
                    except Exception:
                        reset_epoch = int(time.time())
            except Exception:
                reset_epoch = int(time.time())
            # Only log when about to hit the limit (e.g., 1 remaining)
            if rate_remaining == 1:
                wait = max(reset_epoch - int(time.time()), 1)
                if VERBOSE:
                    print(f"Approaching rate limit for {domain}. Waiting {wait} seconds until reset...")
                time.sleep(wait)
        if response.status_code == 200:
            return True
        if response.status_code == 422:
            return True
        if response.status_code == 429:
            retry_after = response.headers.get('Retry-After')
            if retry_after:
                wait = int(retry_after)
            else:
                wait = 2 ** retries
            if VERBOSE:
                print(f"Rate limited (429) for {domain}. Waiting {wait} seconds before retrying...")
            time.sleep(wait)
            retries += 1
            continue
        if VERBOSE:
            print(f"Failed to block {domain}: {response.status_code} {response.text}")
        return False
    if VERBOSE:
        print(f"Max retries exceeded for {domain}. Skipping.")
    return False

def main():
    """Main entry point for the script."""
    sync_blocklist()

if __name__ == "__main__":
    main()
