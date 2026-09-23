from __future__ import annotations

PLAYGROUND_BROWSERS: frozenset[str] = frozenset({"playground", "panel", "admin"})

PREVIEW_PRODUCTION_BROWSER = "preview-production"

PANEL_AUTHENTICATED_BROWSERS: frozenset[str] = PLAYGROUND_BROWSERS | {PREVIEW_PRODUCTION_BROWSER}
