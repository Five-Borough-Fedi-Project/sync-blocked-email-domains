FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install poetry
RUN pip install --no-cache-dir poetry==2.2.1

# Copy poetry files
COPY pyproject.toml poetry.lock* ./

# Configure poetry to not create virtual environments
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --no-dev --no-interaction --no-ansi

# Copy application code
COPY sync_blocked_email_domains ./sync_blocked_email_domains

# Run as non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Set entrypoint
ENTRYPOINT ["poetry", "run", "sync-domains"]
