# sync-blocked-email-domains
sync-blocked-email-domains

This script syncs a list of disposable email domains to a Mastodon server's blocklist using the Mastodon API. It pulls the blocklist from the `disposable-email-domains` Python package and posts each domain to the server.

Usage
-----

Set the following environment variables:
	- `MASTODON_HOST`: The base URL of your Mastodon server (e.g. `https://mastodon.example.com`)
	- `MASTODON_API_TOKEN`: Your Mastodon admin API token
	- `DRY_RUN`: Set to `true` to only print what would happen
	- `VERBOSE`: Set to `true` for detailed logging

Run the script:

		python sync_blocklist.py

Docker
------

You can build and run this as a Docker container. See the Dockerfile for details.

Rate Limiting
-------------

The script checks Mastodon's rate limit headers and will pause if you are about to hit the limit.

Requirements
------------

- Python 3.8+
- `requests`
- `mastodon.py`
- `disposable-email-domains`

Notes
-----

- This is intended to be run as a job or cron task by Mastodon admins.
- It does not remove domains from the blocklist, only adds new ones.
