"""Per-slot browser context pool for safe concurrent scraping."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SlotIdentity:
    proxy: Optional[dict] = None
    ua: str = ""
    platform: str = "Windows"
    sec_ch_ua: str = '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'


@dataclass
class BrowserSlot:
    index: int
    context: Any = None
    identity: SlotIdentity = field(default_factory=SlotIdentity)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def close(self) -> None:
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None
