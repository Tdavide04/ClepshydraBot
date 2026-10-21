import asyncio

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
