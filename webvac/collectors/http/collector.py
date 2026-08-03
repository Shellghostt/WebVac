"""HTTP response collector — headers, cookies, redirect chain."""

from __future__ import annotations

from typing import Any

from webvac.collectors.base import BaseCollector, CollectorContext
from webvac.models.artifacts import BaseArtifact, HTTPResponseArtifact, RedirectHop


def _redirect_chain(response) -> tuple[RedirectHop, ...]:
    if not response:
        return ()
    req = response.request
    urls: list[str] = []
    while req:
        urls.append(req.url)
        req = req.redirected_from
    urls.reverse()
    if not urls:
        urls = [response.url]
    hops = []
    for i, url in enumerate(urls):
        status = response.status if i == len(urls) - 1 else 0
        hops.append(RedirectHop(url=url, status=status))
    return tuple(hops)


def _header_dict(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        return dict(headers)
    except Exception:
        return {k: str(v) for k, v in headers.items()}


class HttpCollector(BaseCollector):
    name = "http"

    def supports(self, ctx: CollectorContext) -> bool:
        return ctx.config.get("collectors", {}).get(self.name, False)

    async def collect(
        self,
        ctx: CollectorContext,
        *,
        page=None,
        response=None,
    ) -> list[BaseArtifact]:
        if response is None and page is not None:
            # Lightweight mock — response may be absent
            return []

        page_url = page.url if page else ctx.base_url
        if response is None:
            return []

        resp_headers = _header_dict(getattr(response, "headers", None))
        req_headers: dict[str, str] = {}
        if hasattr(response, "request") and response.request is not None:
            req_headers = _header_dict(getattr(response.request, "headers", None))
        elif hasattr(response, "request_info"):
            try:
                req_headers = {k: v for k, v in response.request_info.headers.items()}
            except Exception:
                pass

        set_cookies: list[str] = []
        raw = resp_headers.get("set-cookie") or resp_headers.get("Set-Cookie")
        if raw:
            set_cookies.append(raw)
        # Playwright may expose all set-cookie via response.headers array — keep raw dict too

        content_length = None
        cl = resp_headers.get("content-length")
        if cl and cl.isdigit():
            content_length = int(cl)

        artifact = HTTPResponseArtifact(
            page_url=page_url,
            status=getattr(response, "status", 0) or 0,
            http_version="",
            redirect_chain=_redirect_chain(response),
            response_headers=resp_headers,
            request_headers=req_headers,
            set_cookie_raw=tuple(set_cookies),
            content_type=resp_headers.get("content-type", ""),
            content_length=content_length,
        )
        return [artifact]
