"""macOS-specific screen geometry helpers using Quartz APIs."""

from typing import List, Optional, Tuple

import Quartz
from shapely.geometry import box
from shapely.ops import unary_union


def get_global_bounds() -> Tuple[float, float, float, float]:
    """Return a bounding box enclosing **all** physical displays.

    Returns
    -------
    (min_x, min_y, max_x, max_y) tuple in Quartz global coordinates (Y=0 at bottom).
    """
    err, ids, cnt = Quartz.CGGetActiveDisplayList(16, None, None)
    if err != Quartz.kCGErrorSuccess:  # pragma: no cover (defensive)
        raise OSError(f"CGGetActiveDisplayList failed: {err}")

    min_x = min_y = float("inf")
    max_x = max_y = -float("inf")
    for did in ids[:cnt]:
        r = Quartz.CGDisplayBounds(did)
        x0, y0 = r.origin.x, r.origin.y
        x1, y1 = x0 + r.size.width, y0 + r.size.height
        min_x, min_y = min(min_x, x0), min(min_y, y0)
        max_x, max_y = max(max_x, x1), max(max_y, y1)
    return min_x, min_y, max_x, max_y


def get_visible_windows() -> List[Tuple[dict, float]]:
    """List *onscreen* windows with their visible‑area ratio.

    Each tuple is ``(window_info_dict, visible_ratio)`` where *visible_ratio*
    is in ``[0.0, 1.0]``.  Internal system windows (Dock, WindowServer, …) are
    ignored.
    """
    _, _, _, gmax_y = get_global_bounds()

    opts = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListOptionIncludingWindow
    )
    wins = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)

    occupied = None  # running union of opaque regions above the current window
    result: List[Tuple[dict, float]] = []

    for info in wins:
        owner = info.get("kCGWindowOwnerName", "")
        if owner in ("Dock", "WindowServer", "Window Server", "Notification Center", "NotificationCenter"):
            continue

        bounds = info.get("kCGWindowBounds", {})
        x, y, w, h = (
            bounds.get("X", 0),
            bounds.get("Y", 0),
            bounds.get("Width", 0),
            bounds.get("Height", 0),
        )
        if w <= 0 or h <= 0:
            continue  # hidden or minimised

        inv_y = gmax_y - y - h  # Quartz→Shapely Y‑flip (convert top edge)
        poly = box(x, inv_y, x + w, inv_y + h)
        if poly.is_empty:
            continue

        visible = poly if occupied is None else poly.difference(occupied)
        if not visible.is_empty:
            ratio = visible.area / poly.area
            result.append((info, ratio))
            occupied = poly if occupied is None else unary_union([occupied, poly])

    return result


def window_exists(window_id: int) -> bool:
    """Check if a window exists (even if not visible/on-screen).

    Returns
    -------
    bool
        True if window exists (open, minimized, or on different Space), False if closed
    """
    # Query ALL windows, not just on-screen ones
    opts = Quartz.kCGWindowListOptionAll
    wins = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)

    if not wins:
        return False

    for info in wins:
        wid = info.get("kCGWindowNumber")
        if wid == window_id:
            return True
    return False


def get_window_bounds_by_id(window_id: int) -> Optional[Tuple[dict, str]]:
    """Get window bounds and owner by window ID (only for visible on-screen windows).

    Returns
    -------
    tuple of (dict, str) or (None, None)
        (Bounds dict, owner name) if window is visible, (None, None) otherwise.
        Bounds: {'left': x, 'top': y, 'width': w, 'height': h} in screen coordinates (Y=0 at top)
    """
    _, _, _, gmax_y = get_global_bounds()

    opts = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListOptionIncludingWindow
    )
    wins = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)

    for info in wins:
        wid = info.get("kCGWindowNumber")
        if wid == window_id:
            bounds = info.get("kCGWindowBounds", {})
            owner = info.get("kCGWindowOwnerName", "")
            x = int(bounds.get("X", 0))
            y = int(bounds.get("Y", 0))
            w = int(bounds.get("Width", 0))
            h = int(bounds.get("Height", 0))
            if w > 0 and h > 0:
                # CGWindowBounds returns Quartz coordinates (Y=0 at bottom)
                # Convert to screen coordinates (Y=0 at top)
                top = int(gmax_y - y - h)
                return {"left": x, "top": top, "width": w, "height": h}, owner
    return None, None


def get_topmost_window_at_point(x: float, y: float) -> Optional[Tuple[int, str]]:
    """Get the window ID and owner of the topmost window at the given point.

    Parameters:
    - x, y: Mouse coordinates from pynput (Cocoa coordinates, Y=0 at bottom)

    Returns tuple of (window_id, owner_name) or (None, None) if none found.
    """
    # Get ALL on-screen windows in front-to-back Z-order
    opts = Quartz.kCGWindowListOptionOnScreenOnly
    wins = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)

    if not wins:
        return None, None
    
    # Convert Cocoa coords to screen coords for comparison
    _, _, _, gmax_y = get_global_bounds()
    screen_y = gmax_y - y
    
    # Find topmost non-system window at this point
    for win in wins:
        bounds = win.get("kCGWindowBounds", {})
        if not bounds:
            continue

        wx, wy, ww, wh = (
            bounds.get("X", 0),
            bounds.get("Y", 0),
            bounds.get("Width", 0),
            bounds.get("Height", 0),
        )

        # Convert Quartz bounds to screen coords
        win_screen_top = gmax_y - wy - wh

        # Compare with screen coordinates
        x_match = wx <= x <= wx + ww
        y_match = win_screen_top <= screen_y <= win_screen_top + wh

        if x_match and y_match:
            window_id = win.get("kCGWindowNumber")
            owner = win.get("kCGWindowOwnerName", "Unknown")
            layer = win.get("kCGWindowLayer", 0)

            # Skip system UI elements
            is_menubar = layer == Quartz.CGWindowLevelForKey(Quartz.kCGMainMenuWindowLevelKey)
            is_system = owner in ("Dock", "WindowServer", "Window Server", "Notification Center", "NotificationCenter")

            if not is_system and not is_menubar:
                return window_id, owner

    return None, None


def is_app_visible(names) -> bool:
    """Return *True* if **any** window from *names* is at least partially visible."""
    targets = set(names)
    return any(
        info.get("kCGWindowOwnerName", "") in targets and ratio > 0
        for info, ratio in get_visible_windows()
    )


def convert_cocoa_to_screen_y(cocoa_y: float) -> float:
    """Convert Cocoa Y coordinate (Y=0 at bottom) to screen Y coordinate (Y=0 at top)."""
    _, _, _, gmax_y = get_global_bounds()
    return gmax_y - cocoa_y


def convert_screen_to_quartz_y(screen_y: float, height: float) -> int:
    """Convert screen Y coordinate (Y=0 at top) to Quartz Y coordinate (Y=0 at bottom)."""
    _, _, _, gmax_y = get_global_bounds()
    return int(gmax_y - screen_y - height)


def convert_quartz_region_to_screen(region: dict) -> dict:
    """Convert a region from Quartz coordinates (Y=0 at bottom) to screen coordinates (Y=0 at top).
    
    Parameters
    ----------
    region : dict
        {'left': x, 'top': y, 'width': w, 'height': h} in Quartz coordinates
        
    Returns
    -------
    dict
        {'left': x, 'top': y, 'width': w, 'height': h} in screen coordinates
    """
    _, _, _, gmax_y = get_global_bounds()
    return {
        "left": region["left"],
        "top": int(gmax_y - region["top"] - region["height"]),
        "width": region["width"],
        "height": region["height"]
    }

