"""User tab preferences: a sparse title/order overlay on the page registry.

Consumers own the registry (registry.py, no-import contract); the user's
custom tab titles and ordering are a *shell-level* preference and live in a
domain-level Store (``fumiha_hub.tab_overrides``, version 1) shaped
``{page_id: {"title": str, "order": int}}``. Keys reference the live
registry at save time — pages that later disappear leave dead keys that are
simply never matched (the directory only shows registry pages, FXH-F-027)
and are pruned on the next save.

Caching contract (FXH 2026-11-15 A2): the directory view runs on every 5s
shell poll from every open tab, so the overlay is read from Store once per
process (first directory read) and cached under ``hass.data``; saves rewrite
the cache in the same step. The cache key is popped in
``async_remove_entry`` alongside the other hub runtime state (状态配对:
初始化=async_get_prefs 首读 / 使用=DirectoryView / 清理=async_remove_entry).

Store signature verified against the production runtime (HA 2026.1.3,
in-container inspect): ``Store(hass, version, key)`` positional +
``async_save(data)`` + ``async_load()``.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "fumiha_hub.tab_overrides"
STORAGE_VERSION = 1
PREFS_CACHE_KEY = "fumiha_hub_tab_prefs"
MAX_TITLE_LEN = 80


def _sanitize_loaded(data: Any) -> dict[str, dict[str, Any]]:
    """Structural validation for the on-disk overlay (FXH R1 首审 F-605).

    与 base 无关——读取面不做 registry 归一化（消费者临时卸载期间的合法
    死键不得删除，FXH-F-027）；只保证形状安全：条目仅接受 title/order 两
    键且类型合法，其余键丢弃并 WARNING。坏 storage 不再能把目录轮询炸成
    500（旧实现 {**panel, **ov} 整字典展开 + order 非int 时 sort TypeError）。
    """
    if not isinstance(data, dict):
        if data is not None:
            _LOGGER.warning(
                "Tab prefs storage is not a dict (type=%s), ignored",
                type(data).__name__,
            )
        return {}
    out: dict[str, dict[str, Any]] = {}
    for pid, entry in data.items():
        if not isinstance(pid, str) or not isinstance(entry, dict):
            _LOGGER.warning("Tab prefs entry %r malformed, dropped", pid)
            continue
        item: dict[str, Any] = {}
        unknown = set(entry.keys()) - {"title", "order"}
        if unknown:
            _LOGGER.warning("Tab prefs %s drops unknown keys: %s", pid, sorted(unknown))
        if "title" in entry:
            title = entry["title"]
            if isinstance(title, str) and title.strip() and len(title.strip()) <= MAX_TITLE_LEN:
                item["title"] = title.strip()
            else:
                _LOGGER.warning("Tab prefs %s has invalid title, dropped", pid)
        if "order" in entry:
            order = entry["order"]
            if isinstance(order, int) and not isinstance(order, bool):
                item["order"] = order
            else:
                _LOGGER.warning("Tab prefs %s has invalid order, dropped", pid)
        if item:
            out[pid] = item
    return out


async def async_get_prefs(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Return the cached overlay, loading from Store on first access."""
    cached = hass.data.get(PREFS_CACHE_KEY)
    if cached is None:
        store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        cached = _sanitize_loaded(await store.async_load())
        hass.data[PREFS_CACHE_KEY] = cached
        _LOGGER.debug("Tab prefs loaded: %d override(s)", len(cached))
    return cached


async def async_save_prefs(
    hass: HomeAssistant, overrides: dict[str, dict[str, Any]]
) -> None:
    """Persist a full replacement overlay (pre-validated by the view)."""
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    await store.async_save(overrides)
    hass.data[PREFS_CACHE_KEY] = overrides


def normalize_overrides(
    raw: Any, base: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]] | None, str]:
    """Validate a submitted overlay against the live directory base.

    ``base`` maps page_id -> {"title", "order"} of the *un-overridden*
    descriptors. Returns (normalized, "") or (None, reason).

    - payload must be a dict of page_id -> dict;
    - every page_id must exist in ``base`` (saving for a vanished page would
      silently recreate its custom entry on the next directory poll);
    - "title" optional: stripped str, non-empty, <= MAX_TITLE_LEN;
    - "order" optional: int (bool rejected);
    - values equal to the base normalize away — 恢复默认 is just "send the
      base values back", no dedicated delete wire format;
    - entries that normalize to empty are dropped.
    """
    if not isinstance(raw, dict):
        return None, "payload must be a dict of page_id -> {title?, order?}"
    normalized: dict[str, dict[str, Any]] = {}
    for page_id, entry in raw.items():
        if not isinstance(page_id, str) or page_id not in base:
            return None, f"unknown page_id {page_id!r} (not in the current registry)"
        if not isinstance(entry, dict):
            return None, f"override for {page_id} must be a dict"
        item: dict[str, Any] = {}
        if "title" in entry:
            title = entry["title"]
            if not isinstance(title, str) or not title.strip():
                return None, f"title for {page_id} must be a non-empty string"
            title = title.strip()
            if len(title) > MAX_TITLE_LEN:
                return None, f"title for {page_id} exceeds {MAX_TITLE_LEN} characters"
            if title != base[page_id]["title"]:
                item["title"] = title
        if "order" in entry:
            order = entry["order"]
            if not isinstance(order, int) or isinstance(order, bool):
                return None, f"order for {page_id} must be an int"
            if order != base[page_id]["order"]:
                item["order"] = order
        if item:
            normalized[page_id] = item
    return normalized, ""


def apply_overrides(
    panels: list[dict[str, Any]], overrides: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return a new sorted panel list with the overlay applied.

    Read-only on ``panels`` (the directory view re-validates every poll);
    dead override keys (pages no longer registered) never match and never
    resurrect anything. Sort key matches collect_panels: (order, id).
    """
    out: list[dict[str, Any]] = []
    for panel in panels:
        ov = overrides.get(panel["id"])
        if ov:
            panel = dict(panel)
            # F-605：白名单合并（仅 title/order）——覆盖层文件永不触碰
            # module_url/element 等描述符字段（防旧 schema 写回污染）。
            if "title" in ov:
                panel["title"] = ov["title"]
            if "order" in ov:
                panel["order"] = ov["order"]
        out.append(panel)
    out.sort(key=lambda p: (p["order"], p["id"]))
    return out
