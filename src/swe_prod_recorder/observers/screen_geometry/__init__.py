"""Platform-specific screen geometry helpers.

This package contains platform-specific implementations for screen geometry operations:
- screen_geometry_macos.py: macOS implementation using Quartz APIs
- screen_geometry_linux.py: Linux implementation using X11 and mss APIs
"""

import sys

if sys.platform == "darwin":
    from .screen_geometry_macos import *  # noqa: F403, F401
elif sys.platform == "linux":
    from .screen_geometry_linux import *  # noqa: F403, F401
else:
    raise NotImplementedError(f"Platform {sys.platform} not supported")

