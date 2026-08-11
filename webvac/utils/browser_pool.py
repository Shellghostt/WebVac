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
    sec_ch_ua: str = '"Chromium";v="133", "Google Chrome";v="133", "Not-A.Brand";v="99"'
    # Geo pin — keep timezone aligned with lat/lon (and with residential IP when possible)
    city: str = ""
    lat: float = 0.0
    lon: float = 0.0
    timezone: str = ""

    def location_tuple(self) -> Optional[tuple[str, float, float, str]]:
        if self.timezone and self.lat and self.lon:
            return (self.city or self.timezone, self.lat, self.lon, self.timezone)
        return None


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
