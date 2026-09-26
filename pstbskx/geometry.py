"""Pure geometry helpers used by the GUI and unit tests."""
from __future__ import annotations
from typing import Iterable, Tuple

Rect = Tuple[int, int, int, int]


def intersection_area(a: Rect, b: Rect) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    return max(0, x2 - x1) * max(0, y2 - y1)


def clamp_window_rect(
    saved: Rect | None,
    available_screens: Iterable[Rect],
    default_size: tuple[int, int] = (1280, 800),
    minimum_size: tuple[int, int] = (320, 240),
) -> Rect:
    """Return a visible rectangle inside one of the current work areas.

    The first available screen is treated as the primary fallback. If a saved
    window is wholly off-screen (for example after disconnecting a monitor),
    it is recentred on the primary work area. Oversize windows are shrunk.
    """
    screens = list(available_screens)
    if not screens:
        w, h = default_size
        return (40, 40, max(1, w), max(1, h))

    if saved is None:
        sx, sy, sw, sh = screens[0]
        w = min(max(minimum_size[0], default_size[0]), sw)
        h = min(max(minimum_size[1], default_size[1]), sh)
        return (sx + max(0, (sw - w) // 2), sy + max(0, (sh - h) // 2), w, h)

    x, y, w, h = saved
    scored = [(intersection_area(saved, s), s) for s in screens]
    area, screen = max(scored, key=lambda it: it[0])
    if area <= 0 or area < max(1, w * h):
        screen = screens[0]
        sx, sy, sw, sh = screen
        w = min(max(minimum_size[0], w or default_size[0]), sw)
        h = min(max(minimum_size[1], h or default_size[1]), sh)
        return (sx + max(0, (sw - w) // 2), sy + max(0, (sh - h) // 2), w, h)

    sx, sy, sw, sh = screen
    w = min(max(minimum_size[0], w), sw)
    h = min(max(minimum_size[1], h), sh)
    x = min(max(x, sx), sx + sw - w)
    y = min(max(y, sy), sy + sh - h)
    return (x, y, w, h)
