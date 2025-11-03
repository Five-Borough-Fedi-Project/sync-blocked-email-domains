# sync-blocked-email-domains

Automation to make it marginally harder for spammers to create masto.nyc accounts

This tool synchronizes the disposable email domain blocklist from [disposable-email-domains](https://github.com/disposable-email-domains/disposable-email-domains) repository to a Mastodon server using the Admin API.

## Features

- Fetches the latest disposable email domains list from GitHub
- Syncs domains to Mastodon's email domain blocklist via the Admin API
- Supports dry-run mode to preview changes before applying them
- Configurable via environment variables
- Designed to run as a Docker container in Kubernetes cronjobs
- Handles pagination for large blocklists
- Idempotent - only adds domains that don't already exist

## Requirements

- Python 3.9+
- Poetry for dependency management
- Mastodon instance with admin access
- Mastodon API token with `admin:write:email_domain_blocks` scope

## Installation

### Using Poetry

1. Clone this repository:
```bash
git clone https://github.com/Five-Borough-Fedi-Project/sync-blocked-email-domains.git
cd sync-blocked-email-domains
```

2. Install dependencies:
```bash
poetry install
```

3. Create a `.env` file based on `.env.example`:
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Run the sync:
```bash
poetry run sync-domains
```

### Using Docker

1. Build the Docker image:
```bash
docker build -t sync-blocked-email-domains .
```

2. Run the container:
```bash
docker run --env-file .env sync-blocked-email-domains
```

## Configuration

Configuration is done via environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `MASTODON_HOST` | Yes | Full URL to your Mastodon instance (e.g., `https://mastodon.social`) |
| `MASTODON_API_TOKEN` | Yes | API token with `admin:write:email_domain_blocks` scope |
| `DISPOSABLE_DOMAINS_URL` | No | Custom URL for domains list (defaults to disposable-email-domains repo) |
| `DRY_RUN` | No | Set to `true` to preview changes without applying them (default: `false`) |

### Getting a Mastodon API Token

1. Log in to your Mastodon instance as an admin
2. Go to Preferences → Development → New Application
3. Set the application name (e.g., "Email Domain Sync")
4. Select the `admin:write:email_domain_blocks` scope
5. Click "Submit"
6. Copy the access token

## Usage

### Dry Run

To see what domains would be added without making changes:

```bash
DRY_RUN=true poetry run sync-domains
```

### Normal Run

```bash
poetry run sync-domains
```

## Kubernetes Deployment

A complete example CronJob manifest is available in [`examples/kubernetes-cronjob.yaml`](examples/kubernetes-cronjob.yaml).

To deploy:

1. Update the manifest with your Mastodon instance URL
2. Create the secret with your API token:

```bash
kubectl create secret generic mastodon-sync-secret \
  --from-literal=api-token='your_api_token_here' \
  -n mastodon
```

3. Apply the manifest:

```bash
kubectl apply -f examples/kubernetes-cronjob.yaml
```

## Docker Compose

For local testing with Docker Compose, see [`examples/docker-compose.yml`](examples/docker-compose.yml):

```bash
cp .env.example .env
# Edit .env with your configuration
docker-compose -f examples/docker-compose.yml up
```

## Development

### Running Tests

```bash
poetry run pytest
```

### Code Formatting

```bash
poetry run black sync_blocked_email_domains/
```

### Linting

```bash
poetry run flake8 sync_blocked_email_domains/
```

## How It Works

1. **Fetch Disposable Domains**: Downloads the latest list from the disposable-email-domains repository
2. **Get Existing Blocks**: Retrieves current email domain blocks from Mastodon via the Admin API
3. **Calculate Difference**: Determines which domains need to be added
4. **Sync Domains**: Adds missing domains to Mastodon's blocklist

The sync is idempotent - it only adds domains that don't already exist, so it's safe to run multiple times.

## API Reference

The tool uses the Mastodon Admin API:

- [Email Domain Blocks API Documentation](https://docs.joinmastodon.org/methods/admin/email_domain_blocks/)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is provided as-is for use by the Five Borough Fedi Project and the broader Mastodon community.

## Support

For issues and questions, please open an issue on GitHub.
