"""Web layer: directory REST view, static assets and the sidebar shell panel.

Same architecture as the Stockroom / WHA-State-Scanner panels (byte-proven
against HA 2026.1.3 in production): a panel_custom element served from this
integration's static directory — no iframe, no CDN. The shell element
receives the frontend ``hass`` object and polls the directory view below
with ``hass.fetchWithAuth``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import (
    HomeAssistantView,
    StaticPathConfig,
    require_admin,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_loaded_integration

from .const import (
    API_BASE,
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_SIDEBAR_ICON,
    PANEL_SIDEBAR_TITLE,
    PANEL_URL_PATH,
    URL_BASE,
)
from .registry import collect_panels

_LOGGER = logging.getLogger(__name__)

WEB_DATA_KEY = f"{DOMAIN}_web_registered"

# Signature of already-warned invalid descriptors: the shell polls the
# directory every 5s, so repeating the WARNING per read would flood the log
# (~12 lines/min per bad entry) and bury real warnings. First sighting warns;
# repeats downgrade to DEBUG; a changed signature warns again (FXH-F-010).
_WARNED_INVALID: set[tuple[str, str]] = set()


class DirectoryView(HomeAssistantView):
    """GET /api/fumiha_hub/panels — the directory that drives the shell UI."""

    url = f"{API_BASE}/panels"
    name = "api:fumiha_hub:panels"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        panels, skipped = collect_panels(hass)
        # Invalid entries never vanish silently: first sighting is a WARNING,
        # repeats stay visible at DEBUG until the consumer fixes or removes
        # them.
        for key, reason in skipped:
            signature = (key, reason)
            if signature in _WARNED_INVALID:
                _LOGGER.debug("Skipping invalid panel descriptor %s: %s", key, reason)
            else:
                _WARNED_INVALID.add(signature)
                _LOGGER.warning("Skipping invalid panel descriptor %s: %s", key, reason)
        state = hass.data.get(DOMAIN)
        return web.json_response(
            {"dir_rev": state.dir_rev if state else 0, "panels": panels}
        )


async def async_setup_web(hass: HomeAssistant) -> None:
    """Register static assets, panel and API views (once per HA run)."""
    flags: dict = hass.data.setdefault(WEB_DATA_KEY, {})

    if not flags.get("views"):
        hass.http.register_view(DirectoryView())
        flags["views"] = True

    if not flags.get("static"):
        static_dir = Path(__file__).parent / "static"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(static_dir), cache_headers=False)]
        )
        flags["static"] = True

    panels = hass.data.get(frontend.DATA_PANELS) or {}
    if PANEL_URL_PATH not in panels:
        version = "dev"
        try:
            version = async_get_loaded_integration(hass, DOMAIN).version or version
        except Exception:  # noqa: BLE001 — version is only a cache buster
            _LOGGER.debug("Could not resolve integration version for panel URL")
        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            frontend_url_path=PANEL_URL_PATH,
            sidebar_title=PANEL_SIDEBAR_TITLE,
            sidebar_icon=PANEL_SIDEBAR_ICON,
            config={
                "_panel_custom": {
                    "name": PANEL_ELEMENT,
                    "embed_iframe": False,
                    "trust_external": False,
                    "module_url": f"{URL_BASE}/fumiha-hub.js?ver={version}",
                }
            },
            require_admin=True,
        )


@callback
def async_unload_web(hass: HomeAssistant) -> None:
    """Remove the sidebar panel (static paths/views survive entry reloads)."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
