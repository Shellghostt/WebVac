"""
Lightweight per-page network listener for scrape diagnosis.

Attach before ``page.goto()`` and call ``snapshot()`` after load to
get a list of plain dicts suitable for ``dump_network_debug()``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

_RESOURCE_TYPES = frozenset({
    "xhr", "fetch", "websocket", "eventsource", "document", "script",
})
_BODY_PREVIEW_LIMIT = 4096
_WS_MSG_LIMIT = 40
_WS_PAYLOAD_LIMIT = 2000


@dataclass
class _PendingRequest:
    url: str
    method: str
    resource_type: str
    request_headers: dict[str, str]
    post_data: Optional[str] = None
    initiator: str = ""


@dataclass
class _WsSession:
    url: str
    messages: list[dict[str, str]] = field(default_factory=list)


class NetworkListener:
    """Stateful per-page listener. Call ``attach(page)`` before navigation."""

    def __init__(self) -> None:
        self._pending: dict[Any, _PendingRequest] = {}
        self._entries: list[dict[str, Any]] = []
        self._websockets: dict[Any, _WsSession] = {}
        self._page_url: str = ""
        self._page = None

    def attach(self, page, page_url: str = "") -> None:
        self._page = page
        self._page_url = page_url or getattr(page, "url", "")
        page.on("request", self._on_request)
        page.on("response", lambda resp: asyncio.create_task(self._on_response(resp)))
        page.on("requestfailed", self._on_request_failed)
        page.on("requestfinished", lambda req: asyncio.create_task(self._on_finished(req)))
        try:
            page.on("websocket", self._on_websocket)
        except Exception:
            pass

    def _on_websocket(self, ws) -> None:
        url = getattr(ws, "url", "") or ""
        session = _WsSession(url=url)
        self._websockets[ws] = session

        def _clip(payload: Any) -> str:
            if payload is None:
                return ""
            if isinstance(payload, (bytes, bytearray)):
                try:
                    text = payload.decode("utf-8", errors="replace")
                except Exception:
                    text = repr(payload)[:_WS_PAYLOAD_LIMIT]
            else:
                text = str(payload)
            return text[:_WS_PAYLOAD_LIMIT]

        def _add(direction: str, payload: Any) -> None:
            if len(session.messages) >= _WS_MSG_LIMIT:
                return
            session.messages.append({"direction": direction, "data": _clip(payload)})

        try:
            ws.on("framesent", lambda payload: _add("sent", payload))
            ws.on("framereceived", lambda payload: _add("recv", payload))
            ws.on("close", lambda: self._flush_websocket(ws))
        except Exception:
            self._flush_websocket(ws)

    def _flush_websocket(self, ws) -> None:
        session = self._websockets.pop(ws, None)
        if not session:
            return
        page_url = self._page_url or (self._page.url if self._page else session.url)
        self._entries.append({
            "page_url": page_url,
            "request_url": session.url,
            "method": "GET",
            "resource_type": "websocket",
            "request_headers": {},
            "status": 101 if session.messages else 0,
            "response_headers": {},
            "content_type": "websocket",
            "body_preview": f"{len(session.messages)} frame(s)",
            "websocket_messages": session.messages,
        })

    def _on_request(self, request) -> None:
        rtype = request.resource_type
        if rtype not in _RESOURCE_TYPES:
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
        self._pending[request] = _PendingRequest(
            url=request.url,
            method=request.method,
            resource_type=rtype,
            request_headers=dict(request.headers) if request.headers else {},
            post_data=post_data,
            initiator=initiator,
        )

    def _on_request_failed(self, request) -> None:
        rtype = request.resource_type
        pending = self._pending.pop(request, None)
        if not pending and rtype not in _RESOURCE_TYPES:
            return
        if not pending:
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
        page_url = self._page_url or (self._page.url if self._page else pending.url)
        self._entries.append({
            "page_url": page_url,
            "request_url": pending.url,
            "method": pending.method,
            "resource_type": pending.resource_type,
            "request_headers": pending.request_headers,
            "post_data": pending.post_data,
            "status": 0,
            "response_headers": {},
            "content_type": "",
            "body_preview": failure[:_BODY_PREVIEW_LIMIT],
            "initiator": pending.initiator,
        })

    async def _on_response(self, response) -> None:
        request = response.request
        pending = self._pending.get(request)
        status = response.status
        rtype = request.resource_type
        if not pending:
            if rtype not in _RESOURCE_TYPES and status < 400:
                return
            pending = _PendingRequest(
                url=request.url,
                method=request.method,
                resource_type=rtype,
                request_headers=dict(request.headers) if request.headers else {},
            )

        body_preview = ""
        if pending.resource_type in ("xhr", "fetch", "document") or status >= 400:
            try:
                body = await response.body()
                body_preview = body[:_BODY_PREVIEW_LIMIT].decode("utf-8", errors="replace")
            except Exception:
                pass
        resp_headers = dict(response.headers) if response.headers else {}
        page_url = self._page_url or (self._page.url if self._page else pending.url)
        self._entries.append({
            "page_url": page_url,
            "request_url": pending.url,
            "method": pending.method,
            "resource_type": pending.resource_type,
            "request_headers": pending.request_headers,
            "post_data": pending.post_data,
            "status": status,
            "response_headers": resp_headers,
            "content_type": resp_headers.get("content-type", ""),
            "body_preview": body_preview,
            "initiator": pending.initiator,
        })

    async def _on_finished(self, request) -> None:
        self._pending.pop(request, None)

    async def snapshot(self) -> list[dict[str, Any]]:
        """Return all captured entries as plain dicts."""
        for ws in list(self._websockets.keys()):
            self._flush_websocket(ws)
        await asyncio.sleep(0.2)
        return list(self._entries)
