"""Linux-specific screen geometry helpers using X11 and mss APIs.

Supports both X11 and Wayland:
- X11: Uses wmctrl and xwininfo for window management
- Wayland: Uses graceful fallbacks (window management features limited)
- Both: mss works for screen capture on both X11 and Wayland
"""

import os
from typing import List, Optional, Tuple

import mss


def _is_wayland() -> bool:
    """Detect if running on Wayland display server.
    
    Returns
    -------
    bool
        True if running on Wayland, False if X11 or unknown
    """
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    return session_type == "wayland" or wayland_display is not None


def get_global_bounds() -> Tuple[float, float, float, float]:
    """Return a bounding box enclosing **all** physical displays.

    Works on both X11 and Wayland using mss (which supports both).

    Returns
    -------
    (min_x, min_y, max_x, max_y) tuple in screen coordinates (Y=0 at top).
    """
    with mss.mss() as sct:
        min_x = min_y = float("inf")
        max_x = max_y = -float("inf")
        # Skip monitor 0 (all monitors combined)
        for monitor in sct.monitors[1:]:
            x0 = monitor["left"]
            y0 = monitor["top"]
            x1 = x0 + monitor["width"]
            y1 = y0 + monitor["height"]
            min_x, min_y = min(min_x, x0), min(min_y, y0)
            max_x, max_y = max(max_x, x1), max(max_y, y1)
        return min_x, min_y, max_x, max_y


def get_visible_windows() -> List[Tuple[dict, float]]:
    """List *onscreen* windows with their visible‑area ratio.

    Each tuple is ``(window_info_dict, visible_ratio)`` where *visible_ratio*
    is in ``[0.0, 1.0]``.  Internal system windows are ignored.

    Note: Currently returns empty list. Can be enhanced later with X11 window queries.
    """
    # On Linux, return empty list for now (not critical for basic functionality)
    # Can be enhanced later with X11 window queries if needed
    return []


def window_exists(window_id: int) -> bool:
    """Check if a window exists (even if not visible/on-screen).

    Returns
    -------
    bool
        True if window exists (open, minimized, or on different Space), False if closed
    """
    # On Wayland, window management APIs are not available
    # Assume window exists (conservative approach to prevent premature stopping)
    if _is_wayland():
        return True
    
    # On X11, try to query window via xwininfo
    try:
        from ..window.pyxsys.xwininfo import read_xwin_tree
        x_tree = read_xwin_tree()
        x_win = x_tree.select_id(window_id)
        return x_win is not None
    except Exception:
        # If we can't verify, assume it exists (conservative)
        return True


def get_window_bounds_by_id(window_id: int) -> Optional[Tuple[dict, str]]:
    """Get window bounds and owner by window ID (only for visible on-screen windows).

    Returns
    -------
    tuple of (dict, str) or (None, None)
        (Bounds dict, owner name) if window is visible, (None, None) otherwise.
        Bounds: {'left': x, 'top': y, 'width': w, 'height': h} in screen coordinates (Y=0 at top)
    """
    # On Wayland, window management APIs are not available
    if _is_wayland():
        return None, None
    
    # On X11, query window via wmctrl and xwininfo
    try:
        from ..window.pyxsys.xwininfo import read_xwin_tree
        from ..window.pyxsys.wmctrl import read_wmctrl_listings
        
        x_tree = read_xwin_tree()
        wm_territory = read_wmctrl_listings()
        wm_territory.xref_x_session(x_tree)
        
        # Find window by ID
        for wm_win in wm_territory.windows:
            if wm_win.win_id == window_id and hasattr(wm_win, "x_win_id"):
                x_win = x_tree.select_id(wm_win.x_win_id)
                if x_win and x_win.geom:
                    # X11 coordinates are already Y=0 at top, no conversion needed
                    return {
                        "left": int(x_win.geom.abs_x),
                        "top": int(x_win.geom.abs_y),
                        "width": int(x_win.geom.width),
                        "height": int(x_win.geom.height),
                    }, wm_win.title or "Unknown"
        return None, None
    except Exception:
        return None, None


def get_topmost_window_at_point(x: float, y: float) -> Optional[Tuple[int, str]]:
    """Get the window ID and owner of the topmost window at the given point.

    Parameters:
    - x, y: Mouse coordinates from pynput (screen coordinates, Y=0 at top)

    Returns tuple of (window_id, owner_name) or (None, None) if none found.
    """
    # On Wayland, window management APIs are not available
    if _is_wayland():
        return None, None
    
    # On X11, query windows via wmctrl and xwininfo
    try:
        from ..window.pyxsys.xwininfo import read_xwin_tree
        from ..window.pyxsys.wmctrl import read_wmctrl_listings
        
        x_tree = read_xwin_tree()
        wm_territory = read_wmctrl_listings()
        wm_territory.xref_x_session(x_tree)
        
        # Find topmost window at point (windows are already in Z-order from X11)
        for wm_win in wm_territory.windows:
            if hasattr(wm_win, "x_win_id"):
                x_win = x_tree.select_id(wm_win.x_win_id)
                if x_win and x_win.geom:
                    wx = x_win.geom.abs_x
                    wy = x_win.geom.abs_y
                    ww = x_win.geom.width
                    wh = x_win.geom.height
                    
                    # Check if point is in window bounds
                    if wx <= x <= wx + ww and wy <= y <= wy + wh:
                        return wm_win.win_id, wm_win.title or "Unknown"
        return None, None
    except Exception:
        return None, None


def is_app_visible(names) -> bool:
    """Return *True* if **any** window from *names* is at least partially visible."""
    # On Wayland, window management APIs are not available
    if _is_wayland():
        return False
    
    # On X11, check via wmctrl
    try:
        from ..window.pyxsys.wmctrl import read_wmctrl_listings
        targets = set(names)
        wm_territory = read_wmctrl_listings()
        for wm_win in wm_territory.windows:
            if wm_win.title in targets:
                return True
        return False
    except Exception:
        # If we can't check, return False (conservative)
        return False


def convert_cocoa_to_screen_y(cocoa_y: float) -> float:
    """Convert Cocoa Y coordinate (Y=0 at bottom) to screen Y coordinate (Y=0 at top).
    
    On Linux, this is a no-op since pynput already returns Y=0 at top.
    """
    return cocoa_y


def convert_screen_to_quartz_y(screen_y: float, height: float) -> int:
    """Convert screen Y coordinate (Y=0 at top) to Quartz Y coordinate (Y=0 at bottom).
    
    On Linux, this is a no-op since mss uses Y=0 at top.
    """
    return int(screen_y)


def convert_quartz_region_to_screen(region: dict) -> dict:
    """Convert a region from Quartz coordinates (Y=0 at bottom) to screen coordinates (Y=0 at top).
    
    On Linux, this is a no-op since regions are already in screen coordinates (Y=0 at top).
    
    Parameters
    ----------
    region : dict
        {'left': x, 'top': y, 'width': w, 'height': h} in X11/screen coordinates
        
    Returns
    -------
    dict
        {'left': x, 'top': y, 'width': w, 'height': h} in screen coordinates (no conversion needed)
    """
    return region.copy()

