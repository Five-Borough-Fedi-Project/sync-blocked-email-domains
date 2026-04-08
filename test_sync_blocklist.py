"""Tests for sync_blocklist.py."""

import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

import sync_blocklist


# --- fetch_disposable_domains ---

def test_fetch_disposable_domains_success(requests_mock):
    url = "https://example.com/domains.txt"
    requests_mock.get(url, text="foo.com\nbar.org\n  baz.net  \n")
    result = sync_blocklist.fetch_disposable_domains(urls=[url])
    assert result == {"foo.com", "bar.org", "baz.net"}


def test_fetch_disposable_domains_lowercases(requests_mock):
    url = "https://example.com/domains.txt"
    requests_mock.get(url, text="FOO.COM\nBar.Org\n")
    result = sync_blocklist.fetch_disposable_domains(urls=[url])
    assert result == {"foo.com", "bar.org"}


def test_fetch_disposable_domains_skips_blank_lines(requests_mock):
    url = "https://example.com/domains.txt"
    requests_mock.get(url, text="foo.com\n\n\nbar.org\n   \n")
    result = sync_blocklist.fetch_disposable_domains(urls=[url])
    assert result == {"foo.com", "bar.org"}


def test_fetch_disposable_domains_merges_multiple_urls(requests_mock):
    url1 = "https://example.com/list1.txt"
    url2 = "https://example.com/list2.txt"
    requests_mock.get(url1, text="a.com\nb.com\n")
    requests_mock.get(url2, text="b.com\nc.com\n")
    result = sync_blocklist.fetch_disposable_domains(urls=[url1, url2])
    assert result == {"a.com", "b.com", "c.com"}


def test_fetch_disposable_domains_http_error_returns_partial(requests_mock):
    url1 = "https://example.com/good.txt"
    url2 = "https://example.com/bad.txt"
    requests_mock.get(url1, text="a.com\n")
    requests_mock.get(url2, status_code=500)
    result = sync_blocklist.fetch_disposable_domains(urls=[url1, url2])
    assert result == {"a.com"}


def test_fetch_disposable_domains_connection_error_returns_empty():
    url = "https://unreachable.invalid/domains.txt"
    with patch("sync_blocklist.requests.get", side_effect=requests.ConnectionError("fail")):
        result = sync_blocklist.fetch_disposable_domains(urls=[url])
    assert result == set()


def test_fetch_disposable_domains_defaults_to_module_urls():
    with patch("sync_blocklist.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.text = "x.com\n"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        sync_blocklist.fetch_disposable_domains()
        assert mock_get.call_count == len(sync_blocklist.DISPOSABLE_DOMAINS_URLS)


# --- get_mastodon_blocklist ---

def test_get_mastodon_blocklist():
    mock_mastodon = MagicMock()
    page1 = [{"domain": "spam1.com"}, {"domain": "spam2.com"}]
    page2 = [{"domain": "spam3.com"}]
    mock_mastodon.admin_email_domain_blocks.return_value = page1
    mock_mastodon.fetch_next.side_effect = [page2, None]
    with patch("sync_blocklist.Mastodon", return_value=mock_mastodon):
        result = sync_blocklist.get_mastodon_blocklist()
    assert result == {"spam1.com", "spam2.com", "spam3.com"}


# --- log_summary ---

def test_log_summary(capsys):
    with patch("sync_blocklist.pkg_version", return_value="1.0.0"):
        sync_blocklist.log_summary(10, 5, 100, 2, 1)
    output = capsys.readouterr().out
    assert "Domains successfully added: 10" in output
    assert "Domains removed: 5" in output
    assert "Domains already blocked: 100" in output
    assert "Domains failed to add: 2" in output
    assert "Domains failed to remove: 1" in output
    assert "1.0.0" in output


# --- add_domains ---

def test_add_domains_adds_new(monkeypatch):
    monkeypatch.setattr(sync_blocklist, "DRY_RUN", False)
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    mock_mastodon = MagicMock()
    mock_mastodon.ratelimit_remaining = 100
    mock_mastodon.ratelimit_reset = time.time() + 300
    added, already, failed = sync_blocklist.add_domains(
        mock_mastodon, {"new.com"}, set()
    )
    assert added == 1
    assert already == 0
    assert failed == 0
    mock_mastodon.admin_create_email_domain_block.assert_called_once_with("new.com")


def test_add_domains_skips_existing(monkeypatch):
    monkeypatch.setattr(sync_blocklist, "DRY_RUN", False)
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    mock_mastodon = MagicMock()
    mock_mastodon.ratelimit_remaining = 100
    mock_mastodon.ratelimit_reset = time.time() + 300
    added, already, failed = sync_blocklist.add_domains(
        mock_mastodon, {"existing.com"}, {"existing.com"}
    )
    assert added == 0
    assert already == 1
    assert failed == 0


def test_add_domains_dry_run(monkeypatch):
    monkeypatch.setattr(sync_blocklist, "DRY_RUN", True)
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    mock_mastodon = MagicMock()
    added, already, failed = sync_blocklist.add_domains(
        mock_mastodon, {"new.com"}, set()
    )
    assert added == 0
    mock_mastodon.admin_create_email_domain_block.assert_not_called()


def test_add_domains_handles_failure(monkeypatch):
    monkeypatch.setattr(sync_blocklist, "DRY_RUN", False)
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    mock_mastodon = MagicMock()
    mock_mastodon.ratelimit_remaining = 100
    mock_mastodon.ratelimit_reset = time.time() + 300
    mock_mastodon.admin_create_email_domain_block.side_effect = Exception("API error")
    added, already, failed = sync_blocklist.add_domains(
        mock_mastodon, {"fail.com"}, set()
    )
    assert added == 0
    assert failed == 1


# --- remove_domains ---

def test_remove_domains_removes(monkeypatch):
    monkeypatch.setattr(sync_blocklist, "DRY_RUN", False)
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    mock_mastodon = MagicMock()
    mock_mastodon.ratelimit_remaining = 100
    mock_mastodon.ratelimit_reset = time.time() + 300
    removed, failed = sync_blocklist.remove_domains(mock_mastodon, {"old.com"})
    assert removed == 1
    assert failed == 0
    mock_mastodon.admin_delete_email_domain_block.assert_called_once_with("old.com")


def test_remove_domains_dry_run(monkeypatch):
    monkeypatch.setattr(sync_blocklist, "DRY_RUN", True)
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    mock_mastodon = MagicMock()
    removed, failed = sync_blocklist.remove_domains(mock_mastodon, {"old.com"})
    assert removed == 0
    mock_mastodon.admin_delete_email_domain_block.assert_not_called()


def test_remove_domains_handles_failure(monkeypatch):
    monkeypatch.setattr(sync_blocklist, "DRY_RUN", False)
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    mock_mastodon = MagicMock()
    mock_mastodon.ratelimit_remaining = 100
    mock_mastodon.ratelimit_reset = time.time() + 300
    mock_mastodon.admin_delete_email_domain_block.side_effect = Exception("API error")
    removed, failed = sync_blocklist.remove_domains(mock_mastodon, {"fail.com"})
    assert removed == 0
    assert failed == 1


# --- handle_rate_limit ---

def test_handle_rate_limit_waits_when_near_limit(monkeypatch):
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    mock_mastodon = MagicMock()
    mock_mastodon.ratelimit_remaining = 1
    mock_mastodon.ratelimit_reset = time.time() + 5
    with patch("sync_blocklist.time.sleep") as mock_sleep:
        sync_blocklist.handle_rate_limit(mock_mastodon, "test.com")
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] >= 1


def test_handle_rate_limit_no_wait_when_plenty_remaining(monkeypatch):
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    mock_mastodon = MagicMock()
    mock_mastodon.ratelimit_remaining = 100
    mock_mastodon.ratelimit_reset = time.time() + 300
    with patch("sync_blocklist.time.sleep") as mock_sleep:
        sync_blocklist.handle_rate_limit(mock_mastodon, "test.com")
        mock_sleep.assert_not_called()


# --- sync_blocklist ---

def test_sync_blocklist_dry_run(monkeypatch, requests_mock):
    monkeypatch.setattr(sync_blocklist, "DRY_RUN", True)
    monkeypatch.setattr(sync_blocklist, "VERBOSE", False)
    monkeypatch.setattr(sync_blocklist, "MASTODON_HOST", "https://mastodon.example")
    monkeypatch.setattr(sync_blocklist, "MASTODON_API_TOKEN", "fake-token")

    for url in sync_blocklist.DISPOSABLE_DOMAINS_URLS:
        requests_mock.get(url, text="remote.com\n")

    mock_mastodon = MagicMock()
    page = [{"domain": "old.com"}]
    mock_mastodon.admin_email_domain_blocks.return_value = page
    mock_mastodon.fetch_next.return_value = None

    with patch("sync_blocklist.Mastodon", return_value=mock_mastodon):
        sync_blocklist.sync_blocklist()

    mock_mastodon.admin_create_email_domain_block.assert_not_called()
    mock_mastodon.admin_delete_email_domain_block.assert_not_called()
