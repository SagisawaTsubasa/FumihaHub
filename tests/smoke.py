"""Fumiha Hub smoke test — no HA installation required.

Stubs the homeassistant module tree (same approach as the WHA-State-Scanner
smoke suite) and drives the hub end-to-end:

  1. import chain of every hub module
  2. descriptor validation rules
  3. entry setup/unload/reload: idempotent web flags, panel cache buster,
     bus listener attach/detach
  4. registry -> directory view: sorting, invalid entries skipped but logged,
     revision bumps on page-changed events
  5. config flow: first create, duplicate aborts already_configured
  6. static assets exist and the shell file registers its element

Usage: python tests/smoke.py
Exit code 0 = pass; anything else prints the failure.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = "custom_components.fumiha_hub"
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok  {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"FAIL  {name}: {detail}")


# ---------------------------------------------------------------------------
# Stub of the homeassistant module tree (only what the hub imports).
# ---------------------------------------------------------------------------

def _mod(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


ha = _mod("homeassistant")
ha.__path__ = []  # mark as package

ha_const = _mod("homeassistant.const")
ha_const.__getattr__ = lambda name: name  # any CONF_* resolves to itself

ha_core = _mod("homeassistant.core")


class _Event:
    def __init__(self, data=None):
        self.data = data or {}


ha_core.Event = _Event
ha_core.HomeAssistant = type("HomeAssistant", (), {})
ha_core.callback = lambda f: f

ha_ce = _mod("homeassistant.config_entries")
ha_ce.ConfigEntry = type("ConfigEntry", (), {})
ha_ce.ConfigFlowResult = dict

_CONFIGURED: set[str] = set()


class _AbortFlow(Exception):
    """Mirrors data_entry_flow.AbortFlow: aborts RAISE, never return."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _ConfigFlow:
    """Stub mirroring the pieces of HA's ConfigFlow the hub flow relies on.

    Faithful to real semantics: _abort_if_unique_id_configured raises
    (real HA raises AbortFlow), and the loaded-integration lookup is sync
    (real HA raises IntegrationNotLoaded when missing).
    """

    def __init_subclass__(cls, **kwargs):
        pass

    async def async_set_unique_id(self, unique_id):
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        if getattr(self, "_unique_id", None) in _CONFIGURED:
            raise _AbortFlow("already_configured")

    def async_create_entry(self, title, data):
        if getattr(self, "_unique_id", None):
            _CONFIGURED.add(self._unique_id)
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, step_id):
        return {"type": "form", "step_id": step_id}


ha_ce.ConfigFlow = _ConfigFlow

ha_components = _mod("homeassistant.components")
ha_components.__path__ = []

# --- homeassistant.components.frontend -------------------------------------

ha_frontend = _mod("homeassistant.components.frontend")
ha_frontend.DATA_PANELS = "frontend_panels"  # hass.data key in real HA


def _fe_register(hass, **kwargs):
    panels = hass.data.setdefault(ha_frontend.DATA_PANELS, {})
    panels[kwargs["frontend_url_path"]] = kwargs


def _fe_remove(hass, url_path, warn_if_unknown=True):
    hass.data.setdefault(ha_frontend.DATA_PANELS, {}).pop(url_path, None)


ha_frontend.async_register_built_in_panel = _fe_register
ha_frontend.async_remove_panel = _fe_remove

# --- homeassistant.components.http ------------------------------------------

ha_http = _mod("homeassistant.components.http")


class _StaticPathConfig:
    def __init__(self, url_path, path, cache_headers=True):
        self.url_path = url_path
        self.path = path
        self.cache_headers = cache_headers


class _HomeAssistantView:
    # Real HA implements caching in this base; our views only declare class
    # attributes plus handlers, so an empty base is faithful enough here.
    requires_auth = False


def _require_admin(func):
    # Mark the handler so tests can assert the decorator actually ran here
    # (real HA's require_admin wraps the call; the marker stands in for it).
    func._require_admin_applied = True
    return func


ha_http.HomeAssistantView = _HomeAssistantView
ha_http.StaticPathConfig = _StaticPathConfig
ha_http.require_admin = _require_admin

# --- homeassistant.loader ----------------------------------------------------

ha_loader = _mod("homeassistant.loader")
_VERSIONS = {"fumiha_hub": "0.1.0"}


def _get_loaded_integration(hass, domain):
    class _Integration:
        version = _VERSIONS.get(domain)

    return _Integration()


ha_loader.async_get_loaded_integration = _get_loaded_integration

# --- aiohttp.web stub (never depend on a real aiohttp being installed) ------

aiohttp = _mod("aiohttp")
aio_web = _mod("aiohttp.web")


class _Response:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status = status

    def json_dumps(self):
        return json.dumps(self.payload)


def _json_response(data, status=200):
    return _Response(payload=data, status=status)


aio_web.Request = type("Request", (), {})
aio_web.Response = _Response
aio_web.json_response = _json_response


# ---------------------------------------------------------------------------
# Fake hass
# ---------------------------------------------------------------------------


class FakeBus:
    def __init__(self):
        self.listeners = []

    def async_listen(self, event_type, handler):
        self.listeners.append((event_type, handler))
        return lambda: self.listeners.remove((event_type, handler))


class FakeHttp:
    def __init__(self):
        self.views = []
        self.static = []

    def register_view(self, view):
        self.views.append(view)

    async def async_register_static_paths(self, configs):
        self.static.extend(configs)


class FakeConfigEntries:
    def async_get_entry(self, entry_id):
        return None


class FakeHass:
    def __init__(self):
        self.data = {}
        self.bus = FakeBus()
        self.http = FakeHttp()
        self.config_entries = FakeConfigEntries()


class FakeRequest:
    def __init__(self, hass):
        self.app = {"hass": hass}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def main_async() -> None:
    # 1. import chain ------------------------------------------------------
    init_mod = importlib.import_module(PKG)
    const_mod = importlib.import_module(PKG + ".const")
    registry_mod = importlib.import_module(PKG + ".registry")
    web_mod = importlib.import_module(PKG + ".web")  # kept: view-gate asserts below
    flow_mod = importlib.import_module(PKG + ".config_flow")
    check("import chain", True)

    # 2. descriptor validation --------------------------------------------
    validate = registry_mod.validate_descriptor
    good = {
        "id": "luxbalance.main",
        "title": "亮度均衡",
        "icon": "mdi:x",
        "order": 10,
        "version": "0.2.0",
        "module_url": "/lux_balance/page.js?ver=0.2.0",
        "element": "lux-balance-page",
    }
    d, reason = validate(good)
    check("valid descriptor passes", d is not None, reason)
    check("order default", validate({"id": "a.b", "title": "t", "module_url": "/x.js", "element": "x-page"})[0]["order"] == 100, "order must default to 100")

    bad_cases = [
        ("not a dict", "string"),
        ("missing title", {k: v for k, v in good.items() if k != "title"}),
        ("bad element", {**good, "element": "nodash"}),
        ("relative module_url", {**good, "module_url": "http://evil/x.js"}),
        ("protocol-relative module_url", {**good, "module_url": "//evil.com/x.js"}),
        ("backslash module_url", {**good, "module_url": "/\\evil.com/x.js"}),
        ("control-char module_url", {**good, "module_url": "/\t/evil.com/x.js"}),
        ("bad id", {**good, "id": "has space"}),
        ("bool order", {**good, "order": True}),
    ]
    for name, raw in bad_cases:
        d, reason = validate(raw)
        check(f"rejects {name}", d is None, f"expected rejection, got {d}")

    # 3. setup / unload / reload -------------------------------------------
    hass = FakeHass()
    entry = types.SimpleNamespace(entry_id="e1")

    ok = await init_mod.async_setup_entry(hass, entry)
    check("setup returns True", ok is True)
    # 键生命周期契约（FXH-F-029）：setup 即创建（消费者探针语义），remove 即清除
    check(
        "setup creates registry key (hub probe truthiness)",
        registry_mod.REGISTRY_KEY in hass.data,
        "consumers probe by key existence",
    )
    check("views registered", len(hass.http.views) == 1, f"got {len(hass.http.views)}")
    check("static registered", len(hass.http.static) == 1, f"got {len(hass.http.static)}")
    check(
        "static path is URL_BASE",
        hass.http.static[0].url_path == const_mod.URL_BASE,
        hass.http.static[0].url_path,
    )
    check(
        "cache_headers disabled",
        hass.http.static[0].cache_headers is False,
        "must be False",
    )
    panels = hass.data.setdefault(ha_frontend.DATA_PANELS, {})
    check("panel registered", const_mod.PANEL_URL_PATH in panels, str(list(panels)))
    panel_cfg = panels.get(const_mod.PANEL_URL_PATH, {})
    module_url = panel_cfg.get("config", {}).get("_panel_custom", {}).get("module_url", "")
    check(
        "module_url carries manifest version",
        module_url.endswith("?ver=0.1.0"),
        module_url,
    )
    check(
        "require_admin panel",
        panel_cfg.get("require_admin") is True,
        "panel must be admin-only",
    )
    check(
        "bus listener attached",
        len(hass.bus.listeners) == 1
        and hass.bus.listeners[0][0] == registry_mod.BUS_EVENT_PAGE_CHANGED,
        str(hass.bus.listeners),
    )

    ok = await init_mod.async_unload_entry(hass, entry)
    check("unload returns True", ok is True)
    check("panel removed on unload", const_mod.PANEL_URL_PATH not in hass.data[ha_frontend.DATA_PANELS], "must be removed")
    check("listener detached", len(hass.bus.listeners) == 0, str(hass.bus.listeners))

    await init_mod.async_setup_entry(hass, entry)
    check(
        "reload keeps single view registration",
        len(hass.http.views) == 1,
        f"got {len(hass.http.views)}",
    )
    check(
        "reload keeps single static registration",
        len(hass.http.static) == 1,
        f"got {len(hass.http.static)}",
    )
    check(
        "reload re-registers panel",
        const_mod.PANEL_URL_PATH in hass.data[ha_frontend.DATA_PANELS],
        "must be re-registered",
    )
    check(
        "reload keeps single bus listener",
        len(hass.bus.listeners) == 1,
        str(hass.bus.listeners),
    )

    # 只读目录视图不得复活被清掉的 registry 键（FXH-F-027）
    del hass.data[registry_mod.REGISTRY_KEY]
    _view = hass.http.views[0]
    _resp = await _view.get(FakeRequest(hass))
    check(
        "directory view is read-only on the registry key",
        registry_mod.REGISTRY_KEY not in hass.data,
        "view must not re-create the dict",
    )
    # remove 清键（FXH-F-029）
    await init_mod.async_setup_entry(hass, entry)
    assert registry_mod.REGISTRY_KEY in hass.data
    await init_mod.async_remove_entry(hass, entry)
    check(
        "remove deletes registry key (probe falls back)",
        registry_mod.REGISTRY_KEY not in hass.data,
        "probe must go false after hub removal",
    )

    # remove_entry 同时清了 hub 运行态——重新 setup 供后续各节使用
    await init_mod.async_setup_entry(hass, entry)

    # 4. registry -> directory view ----------------------------------------
    hass.data[registry_mod.REGISTRY_KEY] = {
        "luxbalance.main": good,
        "anl.main": {
            "id": "anl.main",
            "title": "夜灯助手",
            "order": 5,
            "version": "2.1.1",
            "module_url": "/auto_night_light/page.js?ver=2.1.1",
            "element": "anl-page",
        },
        "broken": {"oops": True},
    }
    state = hass.data[const_mod.DOMAIN]
    rev_before = state.dir_rev

    view = hass.http.views[0]
    # View gate: the admin/auth declarations are part of the contract — the
    # smoke bypasses the decorators when calling get() directly, so assert
    # the declarations themselves (FXH-F-012).
    check("directory view requires auth", view.requires_auth is True, str(view.requires_auth))
    check(
        "directory view guarded by require_admin",
        getattr(view.get, "_require_admin_applied", False) is True,
        "require_admin marker missing on get()",
    )

    class _Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record):
            self.records.append(record)

    capture = _Capture()
    logging.getLogger("custom_components.fumiha_hub.web").addHandler(capture)
    try:
        web_mod._WARNED_INVALID.clear()
        resp = await view.get(FakeRequest(hass))
        payload = json.loads(resp.json_dumps())
        ids = [p["id"] for p in payload["panels"]]
        check(
            "directory sorted by order",
            ids == ["anl.main", "luxbalance.main"],
            str(ids),
        )
        check("invalid entry skipped", "broken" not in ids, str(ids))
        check("dir_rev exposed", payload["dir_rev"] == rev_before, str(payload["dir_rev"]))
        warnings = [r for r in capture.records if r.levelno == logging.WARNING]
        check(
            "invalid entry logged as WARNING with reason",
            len(warnings) == 1 and "broken" in warnings[0].getMessage(),
            str([r.getMessage() for r in warnings]),
        )

        state.on_page_changed(_Event({"id": "x.main", "action": "register"}))
        resp2 = await view.get(FakeRequest(hass))
        payload2 = json.loads(resp2.json_dumps())
        check(
            "event bumps dir_rev",
            payload2["dir_rev"] == rev_before + 1,
            f"{rev_before} -> {payload2['dir_rev']}",
        )
        # Same invalid signature on the next read: deduped to DEBUG, the
        # WARNING count must stay at 1 (FXH-F-010).
        await view.get(FakeRequest(hass))
        warnings_after = [r for r in capture.records if r.levelno == logging.WARNING]
        check(
            "repeat invalid entry does not re-WARN",
            len(warnings_after) == 1,
            str(len(warnings_after)),
        )
    finally:
        logging.getLogger("custom_components.fumiha_hub.web").removeHandler(capture)

    # 5. config flow --------------------------------------------------------
    flow1 = flow_mod.FumihaHubConfigFlow()
    result = await flow1.async_step_user({})
    check("first user step creates entry", result["type"] == "create_entry", str(result))
    flow2 = flow_mod.FumihaHubConfigFlow()
    try:
        await flow2.async_step_user({})
        check("duplicate aborts already_configured", False, "no abort raised")
    except _AbortFlow as abort:
        check(
            "duplicate aborts already_configured",
            abort.reason == "already_configured",
            abort.reason,
        )

    # 6. static assets -------------------------------------------------------
    static_dir = ROOT / "custom_components" / "fumiha_hub" / "static"
    for fname in ("fumiha-hub.js", "kit.js", "tokens.css"):
        check(f"asset {fname} exists", (static_dir / fname).is_file(), str(static_dir))
    shell_src = (static_dir / "fumiha-hub.js").read_text(encoding="utf-8")
    check(
        "shell registers its element",
        'customElements.define("fumiha-hub-panel"' in shell_src,
        "define call missing",
    )
    kit_src = (static_dir / "kit.js").read_text(encoding="utf-8")
    check(
        "kit installs window.FUMIHA",
        "window.FUMIHA" in kit_src and "defineOnce" in kit_src,
        "contract missing",
    )
    tokens_src = (static_dir / "tokens.css").read_text(encoding="utf-8")
    check(
        "tokens cover shell chrome and components",
        all(cls in tokens_src for cls in (".fx-shell", ".fx-tab", ".cx-table", ".cx-chip", ".fx-toast")),
        "missing classes",
    )
    check(
        "manifest domain matches folder",
        json.loads((ROOT / "custom_components" / "fumiha_hub" / "manifest.json").read_text(encoding="utf-8"))["domain"]
        == "fumiha_hub",
        "domain mismatch",
    )


def main() -> int:
    print("== Fumiha Hub smoke ==")
    asyncio.run(main_async())
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        return 1
    print("\nall green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
