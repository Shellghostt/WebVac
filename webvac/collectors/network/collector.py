"""Network traffic collector — XHR/Fetch/WebSocket listeners (attach before goto)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from webvac.collectors.base import BaseCollector, CollectorContext
from webvac.models.artifacts import BaseArtifact, NetworkRequestArtifact

_STORED_TYPES = frozenset({"xhr", "fetch", "websocket", "eventsource"})
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
    then collect() after page load to flush buffered entries.
    """

    name = "network"

    def __init__(self) -> None:
        self._buffer: Optional[_NetworkBuffer] = None
        self._page = None

    def supports(self, ctx: CollectorContext) -> bool:
        return ctx.config.get("collectors", {}).get(self.name, False)

    def attach(self, page, page_url: str = "") -> None:
        self._page = page
        self._buffer = _NetworkBuffer(page_url=page_url or getattr(page, "url", ""))
        page.on("request", self._on_request)
        page.on("response", lambda resp: asyncio.create_task(self._on_response(resp)))
        page.on("requestfinished", lambda req: asyncio.create_task(self._on_finished(req)))

    def _on_request(self, request) -> None:
        if not self._buffer:
            return
        rtype = request.resource_type
        if rtype not in _STORED_TYPES:
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

    async def _on_response(self, response) -> None:
        if not self._buffer:
            return
        request = response.request
        pending = self._buffer.pending.get(request)
        if not pending:
            rtype = request.resource_type
            if rtype not in _STORED_TYPES:
                return
            pending = _PendingRequest(
                url=request.url,
                method=request.method,
                resource_type=rtype,
                request_headers=dict(request.headers) if request.headers else {},
            )
        body_preview = ""
        if pending.resource_type in ("xhr", "fetch"):
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
                status=response.status,
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
        # Brief wait for async response handlers
        await asyncio.sleep(0.25)
        return list(self._buffer.artifacts)

    def reset(self) -> None:
        self._buffer = None
        self._page = None
