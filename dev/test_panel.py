#!/usr/bin/env python3
"""Playwright smoke for the Fumiha Hub shell (L2) + screenshots (L3 base).

Starts the dev harness server in-process, then drives a real Chromium:

  1. boot: two stub tabs render, provider badges present
  2. default selection mounts the first page (lux stub element live)
  3. deep link  #pn=anl.main  mounts the second page
  4. tab click switches pages and aria-selected follows
  5. rev gate: unchanged rev must NOT rebuild the tab strip
  6. ?failapi=1  -> connection lamp goes err
  7. ?badmodule=1 -> import failure renders an error card with a retry button
  8. screenshots: light/dark x desktop/narrow -> dev/shots/p0-*.png

Usage: python dev/test_panel.py
Exit code 0 = pass. Requires: playwright + chromium installed
(`pip install playwright && playwright install chromium`).
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SHOTS = Path(__file__).resolve().parent / "shots"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  ok  " if cond else "FAIL  ") + name + (f": {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def start_server() -> tuple[ThreadingHTTPServer, int]:
    spec = importlib.util.spec_from_file_location("hub_serve", Path(__file__).parent / "serve.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.HubDevHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def main() -> int:
    from playwright.sync_api import sync_playwright

    server, port = start_server()
    base = f"http://127.0.0.1:{port}"
    SHOTS.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            run_checks(browser, base)
        finally:
            browser.close()
    server.shutdown()

    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        return 1
    print("\nall green")
    return 0


def run_checks(browser, base: str) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # ---- 1+2: boot, tabs, default mount ------------------------------------
    page.goto(base + "/")
    panel = page.locator("fumiha-hub-panel")
    panel.wait_for(state="attached")
    wait_shadow(page, '[data-stub="lux"]', "lux stub page mounts by default")

    tabs = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          return [...p.shadowRoot.querySelectorAll('.fx-tab')].map(t => ({
            id: t.dataset.pageId,
            badge: t.querySelector('.fx-badge').textContent,
            sel: t.getAttribute('aria-selected'),
          }));
        }"""
    )
    check("two tabs rendered", len(tabs) == 2, str(tabs))
    check(
        "provider badges are id first segments",
        [t["badge"] for t in tabs] == ["luxbalance", "anl"],
        str(tabs),
    )
    check("first tab selected", tabs[0]["sel"] == "true", str(tabs))

    # ---- 3: deep link -------------------------------------------------------
    page.evaluate("location.hash = 'pn=anl.main'")
    wait_shadow(page, '[data-stub="anl"]', "deep link #pn=anl.main mounts anl page")
    sel = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          return p.shadowRoot.querySelector('.fx-tab[aria-selected="true"]').dataset.pageId;
        }"""
    )
    check("selection follows deep link", sel == "anl.main", sel)

    # ---- 4: tab click ---------------------------------------------------------
    page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          p.shadowRoot.querySelector('.fx-tab[data-page-id="luxbalance.main"]').click();
        }"""
    )
    wait_shadow(page, '[data-stub="lux"]', "tab click switches back to lux page")
    page.evaluate("location.hash = 'pn=anl.main'")
    wait_shadow(page, '[data-stub="anl"]', "back to anl for next checks")

    # ---- 5: rev gate ----------------------------------------------------------
    # Mark the first tab node, force two polls with an unchanged rev; the
    # marker must survive (tab strip was not rebuilt).
    marked = page.evaluate(
        """async () => {
          const p = document.getElementById('hub');
          p.shadowRoot.querySelector('.fx-tab').dataset.mark = '1';
          await p._poll();
          await p._poll();
          return !!p.shadowRoot.querySelector('.fx-tab[data-mark="1"]');
        }"""
    )
    check("rev gate: unchanged rev keeps tab DOM", marked is True, "tab strip rebuilt")

    # rev CHANGE must rebuild the tab strip (the other half of the gate)
    rebuilt = page.evaluate(
        """async () => {
          const p = document.getElementById('hub');
          p.shadowRoot.querySelector('.fx-tab').dataset.mark = '1';
          window.__bumpRev();
          await p._poll();
          return {
            markGone: !p.shadowRoot.querySelector('.fx-tab[data-mark="1"]'),
            tabs: p.shadowRoot.querySelectorAll('.fx-tab').length,
            stillSel: p.shadowRoot.querySelector('.fx-tab[aria-selected="true"]') !== null,
          };
        }"""
    )
    check(
        "rev change rebuilds tabs, selection kept",
        rebuilt["markGone"] and rebuilt["tabs"] == 2 and rebuilt["stillSel"],
        str(rebuilt),
    )

    # ack toast on stub write button (button lives in the page's own shadow)
    clicked = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const btn = el.shadowRoot && el.shadowRoot.querySelector('[data-stub="anl"] [data-action="trigger"]');
            if (btn) { btn.click(); return true; }
          }
          return false;
        }"""
    )
    check("trigger button found", clicked is True)
    # toast is page-local feedback: the stub passes its own shadowRoot to
    # kit.ack, so probe the nested shadow roots, not just the shell's.
    page.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          if (p.shadowRoot.querySelector('.fx-toast')) return true;
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const t = el.shadowRoot && el.shadowRoot.querySelector('.fx-toast');
            if (t && t.textContent.includes('立即触发')) return true;
          }
          return false;
        }""",
        timeout=3000,
    )
    check("ack toast after write", True)

    check("no page errors so far", not errors, "; ".join(errors[:3]))

    # ---- 6: failapi -------------------------------------------------------------
    page2 = browser.new_page(viewport={"width": 1280, "height": 800})
    page2.goto(base + "/?failapi=1")
    page2.wait_for_timeout(600)
    lamp_cls = page2.evaluate(
        """() => document.getElementById('hub').shadowRoot.querySelector('.fx-lamp').className"""
    )
    check("failapi lamp goes err", "err" in lamp_cls, lamp_cls)
    page2.close()

    # ---- 7: bad module ------------------------------------------------------------
    page3 = browser.new_page(viewport={"width": 1280, "height": 800})
    page3.goto(base + "/?badmodule=1&single=1")
    page3.wait_for_timeout(800)
    card = page3.evaluate(
        """() => {
          const p = document.getElementById('hub');
          const c = p.shadowRoot.querySelector('.fx-error');
          return c ? { msg: c.querySelector('.msg').textContent, retry: !!c.querySelector('button') } : null;
        }"""
    )
    check("bad module shows error card", card is not None, "no .fx-error")
    check(
        "error card carries the fetch failure",
        bool(card) and "Failed to fetch" in card["msg"],
        str(card),
    )
    check("error card has retry", bool(card and card["retry"]), str(card))
    page3.close()

    # ---- reconnect: SAME-INSTANCE detach/reattach (FXH-F-001/F-020) --------
    # HA reuses the panel element across sidebar visits: only a same-instance
    # reconnect exercises the _boot() state resets and the disconnectedCallback
    # seq bump — a freshly created element has null state by construction and
    # would pass even with the fix reverted. The hash still says
    # #pn=anl.main, so the reconnected shell must honor the deep link.
    page.evaluate(
        """() => {
          const el = document.getElementById('hub');
          el.remove();
          document.body.appendChild(el);
        }"""
    )
    wait_shadow(page, '[data-stub="anl"]', "same-instance reconnect rebuilds and honors the deep link")
    tabs_after = page.evaluate(
        """() => document.getElementById('hub').shadowRoot.querySelectorAll('.fx-tab').length"""
    )
    check("reconnected shell re-renders tabs", tabs_after == 2, str(tabs_after))

    # dev server mirrors HA percent-decoding (FXH-F-021): "%6C" is "l"
    resp = page.request.get(base + "/devstub/%6Cux-stub.js?ver=0.0.0")
    check("percent-encoded asset path decodes", resp.status == 200, str(resp.status))
    # NUL byte must be a clean 404, not a handler crash (FXH-F-022)
    resp_nul = page.request.get(base + "/devstub/a%00b.js")
    check("NUL byte path is a clean 404", resp_nul.status == 404, str(resp_nul.status))
    # directory URLs must not list files — HA's static mount never does (FXH-F-024)
    resp_dir = page.request.get(base + "/devstub/")
    check("directory URL is a 404, not a listing", resp_dir.status == 404, str(resp_dir.status))
    page.close()

    # ---- zero panels: content area must show the empty-state card ----------
    page4 = browser.new_page(viewport={"width": 1280, "height": 800})
    page4.goto(base + "/?none=1")
    page4.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          const c = p.shadowRoot.querySelector('.fx-content .fx-empty');
          return c !== null;
        }""",
        timeout=8000,
    )
    check("zero panels render empty-state card", True)
    page4.close()

    # ---- earlyhass: hass assigned before upgrade must still boot ------------
    page4 = browser.new_page(viewport={"width": 1280, "height": 800})
    page4.goto(base + "/?earlyhass=1")
    wait_shadow(page4, '[data-stub="lux"]', "pre-upgrade hass assignment still boots")
    page4.close()

    # ---- 8: screenshots (L3 base) ----------------------------------------------------
    shots = [
        ("/", "p0-light-desktop.png", 1280, 800),
        ("/?dark=1", "p0-dark-desktop.png", 1280, 800),
        ("/", "p0-light-narrow.png", 390, 844),
        ("/?dark=1", "p0-dark-narrow.png", 390, 844),
    ]
    for path, name, w, h in shots:
        shot_page = browser.new_page(viewport={"width": w, "height": h})
        shot_page.goto(base + path)
        shot_page.wait_for_timeout(900)
        shot_page.screenshot(path=str(SHOTS / name), full_page=False)
        shot_page.close()
        check(f"shot {name}", (SHOTS / name).is_file())

    page.close()


def wait_shadow(page, selector: str, label: str, timeout_ms: int = 8000) -> None:
    """wait_for_selector cannot pierce nested shadow roots; poll manually.

    The marker lives in the PAGE element's own shadow, which itself sits in
    the shell's shadow — so probe one level of nesting.
    """
    page.wait_for_function(
        """(sel) => {
          const p = document.getElementById('hub');
          if (!p || !p.shadowRoot) return false;
          if (p.shadowRoot.querySelector(sel)) return true;
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector(sel)) return true;
          }
          return false;
        }""",
        arg=selector,
        timeout=timeout_ms,
    )
    check(label, True)


if __name__ == "__main__":
    raise SystemExit(main())
