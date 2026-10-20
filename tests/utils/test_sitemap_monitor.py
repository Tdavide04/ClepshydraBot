import asyncio
import json
import re

import utils.sitemap_monitor as sitemap_monitor


def run(coro):
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, status: int, text: str):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Minimal fake of aiohttp.ClientSession: only the get() method, used as
    an async context manager - reproduces just the interface used by
    fetch_sitemap_xml()/fetch_page_html()."""

    def __init__(self, status: int = 200, text: str = ""):
        self.status = status
        self.text_value = text
        self.requested_url = None

    def get(self, url):
        self.requested_url = url
        return FakeResponse(self.status, self.text_value)


class TestLoadJsonState:
    def test_returns_a_copy_of_default_when_file_missing(self, tmp_path):
        default = {"latest_url": None, "latest_lastmod": None}
        path = str(tmp_path / "state.json")

        result = sitemap_monitor.load_json_state(path, default)

        assert result == default
        assert result is not default, "must not return the same default object (mutable and shared)"

    def test_loads_existing_file_content(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps({"latest_url": "https://x", "latest_lastmod": "2026-01-01"}), encoding="utf-8"
        )

        result = sitemap_monitor.load_json_state(str(path), {})

        assert result == {"latest_url": "https://x", "latest_lastmod": "2026-01-01"}


class TestSaveJsonState:
    def test_writes_a_file_that_can_be_reloaded(self, tmp_path):
        path = str(tmp_path / "state.json")

        sitemap_monitor.save_json_state(path, {"latest_url": "https://x"})

        assert sitemap_monitor.load_json_state(path, {}) == {"latest_url": "https://x"}

    def test_creates_missing_parent_directories(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "state.json")

        sitemap_monitor.save_json_state(path, {"a": 1})

        assert sitemap_monitor.load_json_state(path, {}) == {"a": 1}

    def test_overwrites_an_existing_file(self, tmp_path):
        path = str(tmp_path / "state.json")

        sitemap_monitor.save_json_state(path, {"a": 1})
        sitemap_monitor.save_json_state(path, {"a": 2})

        assert sitemap_monitor.load_json_state(path, {}) == {"a": 2}

    def test_does_not_leave_the_tmp_file_behind(self, tmp_path):
        path = tmp_path / "state.json"

        sitemap_monitor.save_json_state(str(path), {"a": 1})

        assert not (tmp_path / "state.json.tmp").exists()


class TestPickLatestByLastmod:
    def test_returns_the_entry_with_the_most_recent_lastmod(self):
        entries = {
            "https://a": "2026-08-03T00:00:00Z",
            "https://b": "2026-06-15T00:00:00Z",
        }
        assert sitemap_monitor.pick_latest_by_lastmod(entries) == ("https://a", "2026-08-03T00:00:00Z")

    def test_returns_none_for_empty_input(self):
        assert sitemap_monitor.pick_latest_by_lastmod({}) is None


class TestFetchSitemapXml:
    def test_returns_the_body_on_200(self):
        session = FakeSession(status=200, text="<urlset></urlset>")
        assert run(sitemap_monitor.fetch_sitemap_xml(session)) == "<urlset></urlset>"

    def test_returns_none_on_non_200(self):
        session = FakeSession(status=500, text="")
        assert run(sitemap_monitor.fetch_sitemap_xml(session)) is None


class TestFetchPageHtml:
    def test_returns_the_body_on_200(self):
        session = FakeSession(status=200, text="<html></html>")
        body = run(sitemap_monitor.fetch_page_html(session, "https://example.com/page", log_prefix="TEST"))
        assert body == "<html></html>"

    def test_returns_none_on_non_200(self):
        session = FakeSession(status=404, text="")
        body = run(sitemap_monitor.fetch_page_html(session, "https://example.com/page", log_prefix="TEST"))
        assert body is None


class TestLog:
    def test_prefixes_the_message_with_a_timestamp(self, capsys):
        sitemap_monitor.log("[BAN ANNOUNCEMENT] no change")
        out = capsys.readouterr().out.strip()
        assert re.fullmatch(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[BAN ANNOUNCEMENT\] no change", out)
