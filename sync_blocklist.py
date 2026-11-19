

"""Sync disposable email blocklist to Mastodon server via API.

Fetches the blocklist from disposable_email_domains, compares it to the current
Mastodon blocklist, logs the diff, and syncs the blocklist using the Mastodon API.
Supports dry run mode and handles rate limiting with retries and exponential backoff.
"""

import os
import time
from importlib.metadata import version as pkg_version
import requests
from mastodon import Mastodon
from disposable_email_domains import blocklist

DISPOSABLE_DOMAINS_URLS = [
    "https://raw.githubusercontent.com/disposable/disposable-email-domains/master/domains.txt",
]
# Mastodon's email domain block index defaults to 100 per page and caps
# limit at twice that (limit_param(LIMIT) with LIMIT = 100), so 200 is the
# largest legal page and halves the number of pagination requests.
PAGE_LIMIT = 200
# fetch_disposable_domains swallows network errors and returns whatever it
# managed to read, so a failed or truncated source silently shrinks the desired
# list. Once removals actually work that is not a small bug: desired collapsing
# toward the packaged list alone reads as "almost nothing is disposable any
# more" and would delete most of the live blocklist in one night. On 2026-11-17
# the remote list held 108,547 domains and the package 10,274, so anything
# under this floor means a source did not load rather than that upstream
# shrank. Additions are safe either way; only removals are held back.
MIN_DESIRED_DOMAINS = 50000
MASTODON_HOST = os.getenv('MASTODON_HOST')
MASTODON_API_TOKEN = os.getenv('MASTODON_API_TOKEN')
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() in ('1', 'true', 'yes')
VERBOSE = os.getenv('VERBOSE', 'false').lower() in ('1', 'true', 'yes')

def fetch_disposable_domains(urls=None):
    """Fetch disposable email domain lists from remote URLs.

    Args:
        urls (list): List of URLs to fetch. Defaults to DISPOSABLE_DOMAINS_URLS.

    Returns:
        set: Combined set of disposable email domains from all sources.
    """
    if urls is None:
        urls = DISPOSABLE_DOMAINS_URLS
    all_domains = set()
    for url in urls:
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            domains = set(
                line.strip().lower()
                for line in response.text.splitlines()
                if line.strip()
            )
            print(f"[DEBUG] Fetched {len(domains)} domains from {url}")
            all_domains |= domains
        except Exception as error:
            print(f"Warning: Failed to fetch {url}: {error}")
    return all_domains


def get_mastodon_blocklist(mastodon=None):
    """Fetch the current Mastodon blocklist using Mastodon.py.

    Args:
        mastodon (Mastodon): Existing API client. A new one is built if omitted.

    Returns:
        dict: Mapping of blocked domain to the id of its block. The id is what
            makes a block deletable: the route is
            DELETE /api/v1/admin/email_domain_blocks/:id and the controller
            resolves it with EmailDomainBlock.find(params[:id]), so a domain
            name in that position raises RecordNotFound and the block survives.
    """
    if mastodon is None:
        mastodon = Mastodon(
            api_base_url=MASTODON_HOST,
            access_token=MASTODON_API_TOKEN
        )
    blocks = {}
    page = mastodon.admin_email_domain_blocks(limit=PAGE_LIMIT)
    while page:
        for block in page:
            blocks[block['domain']] = block['id']
        page = mastodon.fetch_next(page)
    return blocks

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

def remove_domains(mastodon, to_remove, current_blocks):
    """Remove domains from Mastodon blocklist.

    Args:
        mastodon (Mastodon): Mastodon API client.
        to_remove (set): Domains to remove.
        current_blocks (dict): Domain to block id, from get_mastodon_blocklist.

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
        block_id = current_blocks.get(domain)
        if block_id is None:
            # Nothing to delete, and no request to spend finding that out.
            failed_count += 1
            if VERBOSE:
                print(f"Failed to remove {domain}: no block id in the current list")
            continue
        try:
            mastodon.admin_delete_email_domain_block(block_id)
            removed_count += 1
            if VERBOSE:
                print(f"Removed domain: {domain} (block {block_id})")
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
    if rl_remaining is not None and rl_reset is not None and rl_remaining <= 1:
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
    pkg_blocklist = set(blocklist)
    print(f"[DEBUG] disposable_email_domains blocklist length: {len(pkg_blocklist)}")
    disposable_domains = fetch_disposable_domains()
    desired_blocklist = pkg_blocklist | disposable_domains
    print(f"[DEBUG] Combined blocklist length: {len(desired_blocklist)}")
    mastodon = Mastodon(
        api_base_url=MASTODON_HOST,
        access_token=MASTODON_API_TOKEN
    )
    if MASTODON_HOST and MASTODON_API_TOKEN:
        current_blocks = get_mastodon_blocklist(mastodon)
    else:
        current_blocks = {}
    current_blocklist = set(current_blocks)
    print(f"[DEBUG] Mastodon current blocklist length: {len(current_blocklist)}")
    to_add = desired_blocklist - current_blocklist
    to_remove = current_blocklist - desired_blocklist
    print(f"[DEBUG] Domains to add: {len(to_add)}")
    print(f"[DEBUG] Domains to remove: {len(to_remove)}")

    if len(desired_blocklist) < MIN_DESIRED_DOMAINS:
        print(
            f"WARNING: the desired blocklist holds only {len(desired_blocklist)} "
            f"domains, under the floor of {MIN_DESIRED_DOMAINS}. A source most "
            f"likely failed to load. Holding back {len(to_remove)} removals so a "
            f"bad fetch cannot empty the blocklist. Additions still apply."
        )
        to_remove = set()

    if to_add:
        added_count, already_count, failed_add = add_domains(mastodon, to_add, current_blocklist)
    else:
        added_count = 0
        # All desired domains are already blocked
        already_count = len(desired_blocklist & current_blocklist)
        failed_add = 0
    removed_count, failed_remove = remove_domains(mastodon, to_remove, current_blocks)
    log_summary(added_count, removed_count, already_count, failed_add, failed_remove)

def main():
    """Main entry point for the script."""
    sync_blocklist()

if __name__ == "__main__":
    main()
