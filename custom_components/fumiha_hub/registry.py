"""Shared page registry between the hub shell and consumer integrations.

Consumers must NOT import this package (no hard dependency, matching the
Codex "pages stay in the modules" rule). The whole contract is two string
constants plus one dict, documented here and duplicated as literals in each
consumer's const.py:

- ``hass.data["fumiha_hub_registry"]``: dict[page_id -> descriptor]
- bus event ``"fumiha_hub_page_changed"`` fired after every register and
  unregister, payload ``{"id": str, "action": "register"|"unregister"}``.
  The hub treats it purely as a "something changed" signal and bumps its
  directory revision.

Descriptor (flat, JSON-safe):

    id          "provider.page" — first segment is the provider badge
    title       display title (zh)
    icon        mdi icon reserved for future use
    order       int, lower first (default 100)
    version     consumer manifest version, used as module cache buster
    module_url  full static URL of the page module, e.g.
                "/lux_balance/page.js?ver=0.2.0"
    element     custom element name defined by the module (must contain '-')
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.core import HomeAssistant

REGISTRY_KEY = "fumiha_hub_registry"
BUS_EVENT_PAGE_CHANGED = "fumiha_hub_page_changed"

REQUIRED_FIELDS = ("id", "title", "module_url", "element")
DEFAULT_ORDER = 100
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$")
_ELEMENT_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def get_registry(hass: HomeAssistant) -> dict[str, Any]:
    """Return the shared registry dict, creating it if absent.

    Safe to call from consumer integrations and from the hub alike; the
    lazily-created dict survives hub entry reloads.
    """
    return hass.data.setdefault(REGISTRY_KEY, {})


def validate_descriptor(raw: Any) -> tuple[dict[str, Any] | None, str]:
    """Validate one raw registry entry.

    Returns (descriptor, "") on success or (None, reason) on failure. The
    caller decides whether a failure is fatal (consumer-side registration)
    or a warning (directory read skips the entry but must log it).
    """
    if not isinstance(raw, dict):
        return None, "descriptor is not a dict"
    for field in REQUIRED_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, f"missing or invalid field '{field}'"
    page_id = raw["id"].strip()
    if not _ID_RE.match(page_id):
        return None, f"id '{page_id}' does not match provider.page naming"
    element = raw["element"].strip()
    if "-" not in element or not _ELEMENT_RE.match(element):
        return None, f"element '{element}' is not a valid custom element name"
    module_url = raw["module_url"].strip()
    # The "/" prefix alone is not enough: WHATWG URL parsing treats a
    # protocol-relative "//host/x.js" (and, in special schemes, backslashes)
    # as a cross-origin URL — the shell would import a third-party module
    # into an admin page (FXH-F-003). URL parsing also strips ASCII
    # tab/newline before anything else, so "/\t/evil.com/x.js" normalizes to
    # the protocol-relative form; reject control characters outright
    # (FXH-F-018).
    if not module_url.startswith("/") or module_url.startswith("//") or "\\" in module_url:
        return None, f"module_url '{module_url}' must be a same-origin absolute path"
    if re.search(r"[\t\n\r\f\v]", module_url):
        return None, f"module_url '{module_url}' contains control characters"
    order = raw.get("order", DEFAULT_ORDER)
    if not isinstance(order, int) or isinstance(order, bool):
        return None, "order must be an int"
    version = raw.get("version", "0")
    if not isinstance(version, str):
        return None, "version must be a string"
    icon = raw.get("icon", "")
    if not isinstance(icon, str):
        return None, "icon must be a string"
    return (
        {
            "id": page_id,
            "title": raw["title"].strip(),
            "icon": icon,
            "order": order,
            "version": version,
            "module_url": module_url,
            "element": element,
        },
        "",
    )


def collect_panels(hass: HomeAssistant) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Assemble the sorted panel directory from the shared registry.

    Returns (panels, skipped) where skipped carries (id_or_repr, reason)
    for every invalid entry so the caller can log it — invalid entries are
    never silently dropped.
    """
    registry = get_registry(hass)
    panels: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    for key, raw in registry.items():
        descriptor, reason = validate_descriptor(raw)
        if descriptor is None:
            skipped.append((str(key), reason))
            continue
        panels.append(descriptor)
    panels.sort(key=lambda p: (p["order"], p["id"]))
    return panels, skipped
