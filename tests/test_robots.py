"""Offline tests for robots.txt handling.

The network download is replaced on the instance, so no socket is opened.
"""

import asyncio

from webvac.utils.robots import RobotsHandler

ROBOTS_BODY = b"User-agent: *\nDisallow: /private\nCrawl-delay: 0\n"


def handler_with(status, body, **kwargs):
    handler = RobotsHandler(**kwargs)
    handler._download_robots = lambda url: (status, body)
    return handler


def test_disallowed_path_is_blocked(tmp_path=None):
    handler = handler_with(200, ROBOTS_BODY)
    asyncio.run(handler.fetch("https://example.com/"))
    assert handler.is_allowed("https://example.com/public") is True
    assert handler.is_allowed("https://example.com/private/secret") is False


def test_missing_robots_allows_everything():
    handler = handler_with(404, None)
    asyncio.run(handler.fetch("https://example.com/"))
    assert handler.is_allowed("https://example.com/anything") is True


def test_forbidden_robots_disallows_everything():
    handler = handler_with(403, b"")
    asyncio.run(handler.fetch("https://example.com/"))
    assert handler.is_allowed("https://example.com/anything") is False


def test_respect_robots_false_allows_everything():
    handler = handler_with(200, ROBOTS_BODY, respect_robots=False)
    asyncio.run(handler.fetch("https://example.com/"))
    assert handler.is_allowed("https://example.com/private/secret") is True


def test_unfetched_origin_defaults_to_allowed():
    handler = RobotsHandler()
    assert handler.is_allowed("https://never-fetched.example/page") is True


def test_origin_parsing():
    assert RobotsHandler._origin("https://sub.example.com/a/b?x=1") == "https://sub.example.com"
    assert RobotsHandler._origin("http://example.com:8080/a") == "http://example.com:8080"
