"""Fumiha Hub — the shared sidebar shell for Fumiha integration panels.

The hub owns navigation, design tokens and page loading; consumer
integrations own their pages (see registry.py for the no-import contract).
Setup is a single global config entry, like the WHA-State-Scanner panel.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN
from .registry import BUS_EVENT_PAGE_CHANGED, REGISTRY_KEY, get_registry
from .web import async_setup_web, async_unload_web

_LOGGER = logging.getLogger(__name__)


class HubState:
    """Per-process hub runtime kept in hass.data across entry reloads."""

    __slots__ = ("dir_rev", "unsub_event")

    def __init__(self) -> None:
        self.dir_rev = 0
        self.unsub_event = None

    @callback
    def on_page_changed(self, event: Event) -> None:
        """Bump the directory revision on any register/unregister signal.

        The payload is intentionally not inspected: consumers with stale or
        foreign events must still invalidate the shell's cached directory,
        and the directory view re-validates every entry on each read.
        """
        self.dir_rev += 1
        _LOGGER.debug(
            "Page registry changed (id=%s action=%s) -> dir_rev=%s",
            event.data.get("id"),
            event.data.get("action"),
            self.dir_rev,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the single shell entry."""
    state = hass.data.get(DOMAIN)
    if state is None:
        state = HubState()
        hass.data[DOMAIN] = state

    # The registry dict must exist as soon as the shell entry is set up:
    # consumers detect the hub by "fumiha_hub_registry" in hass.data, and a
    # lazily-created dict (first directory request) would make that probe
    # wrong in both directions — cold start falls back to standalone panels
    # even though the hub is loaded, and after the hub entry is removed the
    # leftover dict keeps consumers writing descriptors into the void
    # (lux_balance LX-F-001).
    get_registry(hass)

    # Consumers may have loaded (and registered pages) before the hub did;
    # a revision bump here makes the first directory poll pick them up.
    state.dir_rev += 1

    if state.unsub_event is None:
        state.unsub_event = hass.bus.async_listen(
            BUS_EVENT_PAGE_CHANGED, state.on_page_changed
        )

    await async_setup_web(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the shell entry: detach the bus listener and the panel."""
    state: HubState | None = hass.data.get(DOMAIN)
    if state is not None and state.unsub_event is not None:
        state.unsub_event()
        state.unsub_event = None
    async_unload_web(hass)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Entry removed: drop the runtime state.

    The shared registry dict goes with it: consumers probe the hub by the
    key's existence (LX-F-001 lifetime contract), and a leftover dict would
    keep them writing descriptors nobody reads. Consumers re-register their
    fallback panels on their next reload.
    """
    hass.data.pop(DOMAIN, None)
    hass.data.pop(REGISTRY_KEY, None)
