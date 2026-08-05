"""
humanize.py — Human-like pointer, scroll, typing, and idle behaviour for Patchright.

Used by warmup, post-navigation settle, lazy-scroll, and (optionally) consent clicks.
Pure path math is unit-tested without a browser.
"""

from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class HumanizeConfig:
    """Tunables for human-like input. Defaults aim for a calm desktop user."""

    enabled: bool = True
    min_steps: int = 12
    max_steps: int = 28
    move_duration_min: float = 0.18
    move_duration_max: float = 0.55
    overshoot_chance: float = 0.22
    jitter_px: float = 1.4
    idle_min: float = 0.35
    idle_max: float = 1.6
    type_delay_min_ms: int = 45
    type_delay_max_ms: int = 160
    typo_chance: float = 0.04
    scroll_chunk_min: int = 80
    scroll_chunk_max: int = 280
    scroll_pause_min: float = 0.08
    scroll_pause_max: float = 0.35


# Last known cursor position per page id (best-effort; resets if missing).
_cursor: dict[int, tuple[float, float]] = {}


def _page_key(page) -> int:
    return id(page)


def get_cursor(page) -> tuple[float, float]:
    return _cursor.get(_page_key(page), (random.uniform(200, 600), random.uniform(150, 400)))


def set_cursor(page, x: float, y: float) -> None:
    _cursor[_page_key(page)] = (x, y)


def clear_cursor(page) -> None:
    _cursor.pop(_page_key(page), None)


def bezier_point(
    t: float,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> tuple[float, float]:
    """Cubic Bezier at t in [0, 1]."""
    u = 1.0 - t
    x = (
        (u ** 3) * p0[0]
        + 3 * (u ** 2) * t * p1[0]
        + 3 * u * (t ** 2) * p2[0]
        + (t ** 3) * p3[0]
    )
    y = (
        (u ** 3) * p0[1]
        + 3 * (u ** 2) * t * p1[1]
        + 3 * u * (t ** 2) * p2[1]
        + (t ** 3) * p3[1]
    )
    return x, y


def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4 * t * t * t
    return 1 - ((-2 * t + 2) ** 3) / 2


def build_bezier_path(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    steps: int = 20,
    jitter: float = 1.2,
    overshoot: bool = False,
) -> list[tuple[float, float]]:
    """
    Build a curved mouse path from start → end with optional overshoot.
    """
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    dist = math.hypot(dx, dy) or 1.0

    # Control points offset perpendicular to the travel vector.
    nx, ny = -dy / dist, dx / dist
    bend = random.uniform(0.15, 0.45) * dist
    side = random.choice((-1.0, 1.0))
    c1 = (
        sx + dx * random.uniform(0.15, 0.35) + nx * bend * side * random.uniform(0.3, 1.0),
        sy + dy * random.uniform(0.15, 0.35) + ny * bend * side * random.uniform(0.3, 1.0),
    )
    c2 = (
        sx + dx * random.uniform(0.55, 0.85) + nx * bend * (-side) * random.uniform(0.2, 0.8),
        sy + dy * random.uniform(0.55, 0.85) + ny * bend * (-side) * random.uniform(0.2, 0.8),
    )

    target = (ex, ey)
    if overshoot and dist > 40:
        ox = ex + (dx / dist) * random.uniform(6, 18)
        oy = ey + (dy / dist) * random.uniform(6, 18)
        target = (ox, oy)

    points: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = ease_in_out_cubic(i / steps)
        x, y = bezier_point(t, (sx, sy), c1, c2, target)
        if jitter > 0 and i < steps:
            x += random.uniform(-jitter, jitter)
            y += random.uniform(-jitter, jitter)
        points.append((x, y))

    if overshoot and target != (ex, ey):
        # Correct back to the real target with a short straight-ish finish.
        lx, ly = points[-1]
        for j in range(1, 5):
            t = j / 4
            points.append((lx + (ex - lx) * t, ly + (ey - ly) * t))
    else:
        points.append((ex, ey))
    return points


async def idle(page=None, cfg: Optional[HumanizeConfig] = None) -> None:
    cfg = cfg or HumanizeConfig()
    if not cfg.enabled:
        return
    await asyncio.sleep(random.uniform(cfg.idle_min, cfg.idle_max))


async def move_to(
    page,
    x: float,
    y: float,
    *,
    cfg: Optional[HumanizeConfig] = None,
) -> None:
    """Move mouse along a Bezier path to (x, y)."""
    cfg = cfg or HumanizeConfig()
    if not cfg.enabled:
        await page.mouse.move(x, y)
        set_cursor(page, x, y)
        return

    start = get_cursor(page)
    dist = math.hypot(x - start[0], y - start[1])
    steps = max(
        cfg.min_steps,
        min(cfg.max_steps, int(dist / 18) + random.randint(8, 14)),
    )
    overshoot = random.random() < cfg.overshoot_chance and dist > 60
    path = build_bezier_path(
        start, (x, y),
        steps=steps,
        jitter=cfg.jitter_px,
        overshoot=overshoot,
    )
    duration = random.uniform(cfg.move_duration_min, cfg.move_duration_max)
    # Slightly longer for longer distances
    duration *= 0.85 + min(1.4, dist / 900)
    delay = duration / max(len(path), 1)

    for px, py in path:
        await page.mouse.move(px, py)
        await asyncio.sleep(delay * random.uniform(0.75, 1.25))
    set_cursor(page, x, y)


async def click(
    page,
    *,
    x: Optional[float] = None,
    y: Optional[float] = None,
    selector: Optional[str] = None,
    cfg: Optional[HumanizeConfig] = None,
) -> bool:
    """
    Human-like click: move to target, pause, press/release.
    Provide either selector or x/y.
    """
    cfg = cfg or HumanizeConfig()
    tx, ty = x, y
    locator = None
    if selector:
        locator = page.locator(selector).first
        try:
            box = await locator.bounding_box(timeout=2500)
        except Exception:
            box = None
        if not box:
            if cfg.enabled is False:
                try:
                    await locator.click(timeout=2500)
                    return True
                except Exception:
                    return False
            return False
        tx = box["x"] + box["width"] * random.uniform(0.35, 0.65)
        ty = box["y"] + box["height"] * random.uniform(0.35, 0.65)

    if tx is None or ty is None:
        return False

    if cfg.enabled:
        await move_to(page, tx, ty, cfg=cfg)
        await asyncio.sleep(random.uniform(0.05, 0.18))
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.04, 0.12))
        await page.mouse.up()
    else:
        await page.mouse.click(tx, ty)
        set_cursor(page, tx, ty)
    return True


async def scroll_by(
    page,
    delta_y: int,
    *,
    cfg: Optional[HumanizeConfig] = None,
) -> None:
    """Scroll using mouse wheel in irregular chunks (not instant JS scrollTo)."""
    cfg = cfg or HumanizeConfig()
    if not cfg.enabled or delta_y == 0:
        if delta_y:
            await page.mouse.wheel(0, delta_y)
        return

    remaining = abs(delta_y)
    direction = 1 if delta_y > 0 else -1
    # Nudge cursor toward page center-ish so wheel events look natural
    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
    except Exception:
        vp = {"width": 1280, "height": 800}
    cx = vp["width"] * random.uniform(0.35, 0.65)
    cy = vp["height"] * random.uniform(0.35, 0.65)
    await move_to(page, cx, cy, cfg=cfg)

    while remaining > 0:
        chunk = min(remaining, random.randint(cfg.scroll_chunk_min, cfg.scroll_chunk_max))
        await page.mouse.wheel(0, chunk * direction)
        remaining -= chunk
        await asyncio.sleep(random.uniform(cfg.scroll_pause_min, cfg.scroll_pause_max))


async def scroll_page(
    page,
    *,
    amount: Optional[int] = None,
    direction: str = "down",
    cfg: Optional[HumanizeConfig] = None,
) -> None:
    cfg = cfg or HumanizeConfig()
    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
        default_amt = int(vp.get("height", 800) * random.uniform(0.6, 1.1))
    except Exception:
        default_amt = 600
    delta = amount if amount is not None else default_amt
    if direction == "up":
        delta = -abs(delta)
    else:
        delta = abs(delta)
    await scroll_by(page, delta, cfg=cfg)


async def type_text(
    page,
    selector: str,
    text: str,
    *,
    cfg: Optional[HumanizeConfig] = None,
    clear: bool = True,
) -> None:
    """Click into a field and type with variable delays (rare typos)."""
    cfg = cfg or HumanizeConfig()
    await click(page, selector=selector, cfg=cfg)
    await asyncio.sleep(random.uniform(0.08, 0.25))
    if clear:
        try:
            await page.locator(selector).first.fill("")
        except Exception:
            pass

    if not cfg.enabled:
        await page.locator(selector).first.type(text, delay=80)
        return

    for ch in text:
        if cfg.typo_chance > 0 and random.random() < cfg.typo_chance and ch.isalnum():
            wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
            await page.keyboard.type(wrong, delay=random.randint(cfg.type_delay_min_ms, cfg.type_delay_max_ms))
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.04, 0.12))
        await page.keyboard.type(
            ch,
            delay=random.randint(cfg.type_delay_min_ms, cfg.type_delay_max_ms),
        )
        if ch in " .,!?":
            await asyncio.sleep(random.uniform(0.04, 0.14))


async def settle(page, *, cfg: Optional[HumanizeConfig] = None) -> None:
    """
    Post-navigation micro-behaviour: small moves, short idle, light scroll nudge.
    Cheap enough to run on every successful page load.
    """
    cfg = cfg or HumanizeConfig()
    if not cfg.enabled:
        return
    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
        w, h = vp["width"], vp["height"]
    except Exception:
        w, h = 1280, 800

    await idle(page, cfg=HumanizeConfig(
        enabled=True,
        idle_min=max(0.2, cfg.idle_min * 0.5),
        idle_max=max(0.5, cfg.idle_max * 0.7),
    ))
    for _ in range(random.randint(1, 3)):
        await move_to(
            page,
            random.uniform(w * 0.15, w * 0.85),
            random.uniform(h * 0.15, h * 0.75),
            cfg=cfg,
        )
        await asyncio.sleep(random.uniform(0.08, 0.28))
    if random.random() < 0.65:
        await scroll_by(page, random.randint(60, 220), cfg=cfg)
        await asyncio.sleep(random.uniform(0.15, 0.45))


async def skim_page(page, *, cfg: Optional[HumanizeConfig] = None) -> None:
    """Warmup-style skim: scroll down in chunks, pause, scroll back up."""
    cfg = cfg or HumanizeConfig()
    if not cfg.enabled:
        return
    steps = random.randint(2, 4)
    for _ in range(steps):
        await scroll_page(page, direction="down", cfg=cfg)
        await asyncio.sleep(random.uniform(0.4, 1.2))
    await asyncio.sleep(random.uniform(0.6, 1.8))
    for _ in range(random.randint(1, 2)):
        await scroll_page(page, direction="up", cfg=cfg)
        await asyncio.sleep(random.uniform(0.25, 0.7))


def config_from_mapping(data: Optional[dict] = None) -> HumanizeConfig:
    """Build HumanizeConfig from DEFAULT_CONFIG / session_config keys."""
    data = data or {}
    return HumanizeConfig(
        enabled=bool(data.get("humanize", True)),
        idle_min=float(data.get("humanize_idle_min", 0.35)),
        idle_max=float(data.get("humanize_idle_max", 1.6)),
        type_delay_min_ms=int(data.get("typing_delay", 45) or 45),
        type_delay_max_ms=int(data.get("humanize_type_delay_max_ms", 160)),
    )
