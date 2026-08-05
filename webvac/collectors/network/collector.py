"""Network traffic collector — XHR/Fetch/WebSocket (+ scrape-debug document/script).

Attach before page.goto(). Used by:
  - VAPT recon (collectors.network)
  - Always-on scrape diagnosis (network_debug)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from webvac.collectors.base import BaseCollector, CollectorContext
from webvac.models.artifacts import BaseArtifact, NetworkRequestArtifact

_VAPT_TYPES = frozenset({"xhr", "fetch", "websocket", "eventsource"})
_SCRAPE_TYPES = frozenset({
    "xhr", "fetch", "websocket", "eventsource", "document", "script",
})
_BODY_PREVIEW_LIMIT = 4096


@dataclass
class _PendingRequest:
    url: str
    method: str
    resource_type: str
    request_headers: dict[str, str]
    post_data: Optional[str] = None
    initiator: str = ""


@dataclass
class _NetworkBuffer:
    pending: dict[Any, _PendingRequest] = field(default_factory=dict)
    artifacts: list[NetworkRequestArtifact] = field(default_factory=list)
    page_url: str = ""


class NetworkCollector(BaseCollector):
    """
    Stateful per-page collector. Call attach(page) before page.goto(),
    then collect() / snapshot() after load (or on failure) to flush.
    """

    name = "network"

    def __init__(self, *, scrape_debug: bool = False) -> None:
        self.scrape_debug = scrape_debug
        self._types = _SCRAPE_TYPES if scrape_debug else _VAPT_TYPES
        self._buffer: Optional[_NetworkBuffer] = None
        self._page = None

    def supports(self, ctx: CollectorContext) -> bool:
        if self.scrape_debug:
            return bool(ctx.config.get("network_debug", True))
        return ctx.config.get("collectors", {}).get(self.name, False)

    def attach(self, page, page_url: str = "") -> None:
        self._page = page
        self._buffer = _NetworkBuffer(page_url=page_url or getattr(page, "url", ""))
        page.on("request", self._on_request)
        page.on("response", lambda resp: asyncio.create_task(self._on_response(resp)))
        page.on("requestfailed", self._on_request_failed)
        page.on("requestfinished", lambda req: asyncio.create_task(self._on_finished(req)))

    def _want_type(self, rtype: str) -> bool:
        return rtype in self._types

    def _on_request(self, request) -> None:
        if not self._buffer:
            return
        rtype = request.resource_type
        if not self._want_type(rtype):
            return
        post_data = None
        try:
            post_data = request.post_data
        except Exception:
            pass
        initiator = ""
        try:
            init = request.initiator
            if init:
                initiator = str(init.get("type", "")) if isinstance(init, dict) else str(init)
        except Exception:
            pass
        self._buffer.pending[request] = _PendingRequest(
            url=request.url,
            method=request.method,
            resource_type=rtype,
            request_headers=dict(request.headers) if request.headers else {},
            post_data=post_data,
            initiator=initiator,
        )

    def _on_request_failed(self, request) -> None:
        if not self._buffer:
            return
        rtype = request.resource_type
        pending = self._buffer.pending.pop(request, None)
        if not pending and not self._want_type(rtype) and not self.scrape_debug:
            return
        if not pending:
            if not (self.scrape_debug or self._want_type(rtype)):
                return
            pending = _PendingRequest(
                url=request.url,
                method=request.method,
                resource_type=rtype,
                request_headers=dict(request.headers) if request.headers else {},
            )
        failure = ""
        try:
            failure = str(request.failure) if request.failure else "requestfailed"
        except Exception:
            failure = "requestfailed"
        page_url = self._buffer.page_url or (self._page.url if self._page else pending.url)
        self._buffer.artifacts.append(
            NetworkRequestArtifact(
                page_url=page_url,
                request_url=pending.url,
                method=pending.method,
                resource_type=pending.resource_type,
                request_headers=pending.request_headers,
                post_data=pending.post_data,
                status=0,
                response_headers={},
                content_type="",
                body_preview=failure[:_BODY_PREVIEW_LIMIT],
                initiator=pending.initiator,
            )
        )

    async def _on_response(self, response) -> None:
        if not self._buffer:
            return
        request = response.request
        pending = self._buffer.pending.get(request)
        status = response.status
        rtype = request.resource_type
        # In scrape-debug, also keep any failed resource even if type filtered
        if not pending:
            if not (self._want_type(rtype) or (self.scrape_debug and status >= 400)):
                return
            pending = _PendingRequest(
                url=request.url,
                method=request.method,
                resource_type=rtype,
                request_headers=dict(request.headers) if request.headers else {},
            )
        elif not self._want_type(rtype) and not (self.scrape_debug and status >= 400):
            return

        body_preview = ""
        if pending.resource_type in ("xhr", "fetch", "document") or status >= 400:
            try:
                body = await response.body()
                body_preview = body[:_BODY_PREVIEW_LIMIT].decode("utf-8", errors="replace")
            except Exception:
                pass
        resp_headers = dict(response.headers) if response.headers else {}
        page_url = self._buffer.page_url or (self._page.url if self._page else pending.url)
        self._buffer.artifacts.append(
            NetworkRequestArtifact(
                page_url=page_url,
                request_url=pending.url,
                method=pending.method,
                resource_type=pending.resource_type,
                request_headers=pending.request_headers,
                post_data=pending.post_data,
                status=status,
                response_headers=resp_headers,
                content_type=resp_headers.get("content-type", ""),
                body_preview=body_preview,
                initiator=pending.initiator,
            )
        )

    async def _on_finished(self, request) -> None:
        if self._buffer:
            self._buffer.pending.pop(request, None)

    async def collect(
        self,
        ctx: CollectorContext,
        *,
        page=None,
        response=None,
    ) -> list[BaseArtifact]:
        if not self._buffer:
            return []
        if page and not self._buffer.page_url:
            self._buffer.page_url = page.url
        await asyncio.sleep(0.25)
        return list(self._buffer.artifacts)

    async def snapshot(self) -> list[dict[str, Any]]:
        """Return serializable entries for scrape debug dumps."""
        if not self._buffer:
            return []
        await asyncio.sleep(0.2)
        return [a.to_dict() for a in self._buffer.artifacts]

    def reset(self) -> None:
        self._buffer = None
        self._page = None
