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
  9. scroll-ownership layout regression (FXH R1 #1/#2): tall / bare / inline
     stubs — the mounted page element must be the sole vertical scroll
     container, the shell .fx-content must never scroll, and a contract-
     violating inline page must trigger the naming console.warn

Usage: python dev/test_panel.py
Exit code 0 = pass. Requires: playwright + chromium installed
(`pip install playwright && playwright install chromium`).
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
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

    # ---- A1 overscroll regression（FXH 用户反馈 2026-11-15）----------------
    # 标签栏/壳体禁上下橡皮筋：.fx-tabs 显式 overflow-y:hidden+
    # overscroll-behavior:none（竖拖不再把 tab 条当纵向滚动容器、滚动链在
    # tab 条掐断）；.fx-shell 同设；挂载页面元素 inline contain（页面滚到
    # 头不链到文档）。computed style 需 tokens link 加载完成，轮询等掉。
    overscroll = poll_overscroll(page)
    check("A1: .fx-tabs overflow-y hidden",
          overscroll.get("tabsOverflowY") == "hidden", str(overscroll))
    check("A1: .fx-tabs overscroll-behavior none",
          overscroll.get("tabsOverscroll") == "none", str(overscroll))
    check("A1: .fx-shell overscroll-behavior none",
          overscroll.get("shellOverscroll") == "none", str(overscroll))
    check("A1: page element overscroll contain",
          overscroll.get("hostOverscroll") == "contain", str(overscroll))

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

    # ---- narrow: menu button + hass-toggle-menu event (FXH-F-033) ----
    # MockHass page does not set narrow; drive it manually like HA would.
    page.evaluate(
        """async () => {
          const p = document.getElementById('hub');
          window.__menuEvents = [];
          window.addEventListener('hass-toggle-menu',
            (e) => window.__menuEvents.push(e.detail), { once: true });
          p.narrow = true;
          await new Promise((r) => setTimeout(r, 50));
        }"""
    )
    btn = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          const b = p.shadowRoot.querySelector('.fx-menubtn');
          return b ? {visible: b.style.display !== 'none'} : null;
        }"""
    )
    check("narrow=true shows menu button", bool(btn and btn["visible"]), str(btn))
    page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          p.shadowRoot.querySelector('.fx-menubtn').click();
        }"""
    )
    menu_fired = page.evaluate("() => window.__menuEvents")
    check(
        "menu button fires hass-toggle-menu (open)",
        len(menu_fired) == 1 and menu_fired[0].get("open") is True,
        str(menu_fired),
    )
    page.evaluate(
        """async () => {
          const p = document.getElementById('hub');
          p.narrow = false;
          await new Promise((r) => setTimeout(r, 50));
        }"""
    )
    btn2 = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          const b = p.shadowRoot.querySelector('.fx-menubtn');
          return b ? {visible: b.style.display !== 'none'} : null;
        }"""
    )
    check("narrow=false hides menu button", bool(btn2 and not btn2["visible"]), str(btn2))

    # ---- reload window: vanished SELECTED page must not kick the user ----
    # (FXH-F-029/F-030: the vanished id must be the selected one, or the
    # hold branch never executes and the assertions pass on broken code.)
    page.evaluate("() => { location.hash = 'pn=anl.main'; }")
    wait_shadow(page, '[data-stub="anl"]', "anl selected as the baseline")
    page.evaluate("() => { location.hash = 'pn=luxbalance.main'; }")
    wait_shadow(page, '[data-stub="lux"]', "lux selected before vanish")
    page.evaluate("() => window.__vanishLux()")   # selected lux disappears
    page.evaluate("""async () => {
      // _poll has a single-flight guard: a scheduled poll in flight would
      // swallow the manual call — poll until the dir_rev actually moved.
      const p = document.getElementById('hub');
      const before = p._dir ? p._dir.dir_rev : -1;
      for (let i = 0; i < 20; i++) {
        await p._poll();
        if (p._dir && p._dir.dir_rev !== before) break;
        await new Promise((r) => setTimeout(r, 50));
      }
    }""")
    still = page.evaluate("() => location.hash")
    mounted = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          return !!(p.shadowRoot.querySelector('[data-stub="lux"]') ||
                    [...p.shadowRoot.querySelectorAll('*')].some(
                      (el) => el.shadowRoot && el.shadowRoot.querySelector('[data-stub="lux"]')));
        }"""
    )
    check("vanish: selection held for one directory change",
          "pn=luxbalance.main" in still and mounted, f"{still} mounted={mounted}")
    page.evaluate("""async () => {
      const p = document.getElementById('hub');
      const before = p._dir ? p._dir.dir_rev : -1;
      window.__bumpRev();
      for (let i = 0; i < 20; i++) {
        await p._poll();
        if (p._dir && p._dir.dir_rev !== before) break;
        await new Promise((r) => setTimeout(r, 50));
      }
    }""")
    # Bounded fallback (FXH-F-032): selection lands on anl AND the hash is
    # rewritten to match — the shell's "make the URL shareable" step must
    # happen; a variant that holds the stale selection or skips the hash
    # write must fail this wait.
    page.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          const sel = p.shadowRoot.querySelector('.fx-tab[aria-selected="true"]');
          return !!sel && sel.dataset.pageId === 'anl.main'
            && location.hash.indexOf('pn=anl.main') !== -1;
        }""",
        timeout=6000,
    )
    check("next directory change takes the normal fallback", True)

    # ---- directory fully collapsed while selected: honest empty-state card ----
    page.evaluate("() => { location.hash = 'pn=anl.main'; }")
    wait_shadow(page, '[data-stub="anl"]', "anl re-selected before emptyDir test")
    page.evaluate("() => window.__emptyDir()")   # whole directory zeroes out
    page.evaluate("""async () => {
      const p = document.getElementById('hub');
      const before = p._dir ? p._dir.dir_rev : -1;
      for (let i = 0; i < 20; i++) {
        await p._poll();
        if (p._dir && p._dir.dir_rev !== before) break;
        await new Promise((r) => setTimeout(r, 50));
      }
    }""")
    empty_now = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          let stalePage = false;
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector('[data-stub="anl"]')) {
              stalePage = true;
              break;
            }
          }
          return {
            emptyCard: !!p.shadowRoot.querySelector('.fx-content .fx-empty'),
            staleGone: !stalePage,   // the stranded mount must be unmounted
            hash: location.hash,
          };
        }"""
    )
    check("collapsed directory swaps to empty-state card",
          bool(empty_now["emptyCard"] and empty_now["staleGone"]), str(empty_now))

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

    # vanish/emptyDir left the fixture directory collapsed — restore it for
    # the reconnect case below, which needs both tabs present.
    page.evaluate("() => window.__restoreHub()")

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

    # ---- 9: scroll-ownership layout regression (FXH R1 #1/#2) ---------------
    # 满高嵌入契约的行为断言（R1 #1：此前 0 处布局断言，回退本批布局改动
    # L2 仍全绿）。契约：挂载进来的页面元素是唯一纵向滚动容器（block +
    # overflow-y:auto + 内部真实溢出），壳 .fx-content 永不滚动。
    # tall = link tokens 路径；bare = 不 link tokens、自带 :host 契约
    # （stockroom/WHA 形态，R1 #2 的 display:block 前提）；inline = 刻意
    # 违反契约，壳的一次性探测必须 console.warn 指名元素（R1 #2 信号面）。
    page5 = browser.new_page(viewport={"width": 1280, "height": 800})
    page5.goto(base + "/?tall=1")
    wait_shadow(page5, '[data-stub="tall"]', "tall stub mounts (link-tokens path)")
    check_scroll_owner("tall desktop", scroll_probe(page5, "tall"))
    tall_links = page5.evaluate(
        """() => {
          const h = document.getElementById('hub').shadowRoot.querySelector('.fx-page > *');
          return h.shadowRoot.querySelectorAll('link[rel="stylesheet"]').length;
        }"""
    )
    check("tall fixture links tokens (fixture integrity)", tall_links == 1, str(tall_links))

    # 切 tab → 切回：inline 契约由每次 _mount 重新注入，重挂载后归属不变
    page5.evaluate("() => { location.hash = 'pn=anl.main'; }")
    wait_shadow(page5, '[data-stub="anl"]', "switched to anl tab")
    page5.evaluate("() => { location.hash = 'pn=luxbalance.main'; }")
    wait_shadow(page5, '[data-stub="tall"]', "switched back to tall tab")
    check_scroll_owner("tall re-mount", scroll_probe(page5, "tall"))
    page5.close()

    # narrow viewport（内容区 ≈717px）：同一契约在更小的盒上成立
    page6 = browser.new_page(viewport={"width": 390, "height": 800})
    page6.goto(base + "/?tall=1&single=1")
    wait_shadow(page6, '[data-stub="tall"]', "tall stub mounts in narrow viewport")
    check_scroll_owner("tall narrow", scroll_probe(page6, "tall"))
    page6.close()

    # bare fixture：无 tokens link、自带 :host{display:block;height:100%}——
    # inline 契约在「无 tokens」路径同样生效，且不得触发 display:inline 告警
    bare_warns: list[str] = []
    page7 = browser.new_page(viewport={"width": 1280, "height": 800})
    page7.on(
        "console",
        lambda msg: bare_warns.append(msg.text) if msg.type == "warning" else None,
    )
    page7.goto(base + "/?bare=1&single=1")
    wait_shadow(page7, '[data-stub="bare"]', "bare stub mounts (no-tokens path)")
    check_scroll_owner("bare desktop", scroll_probe(page7, "bare"))
    bare_links = page7.evaluate(
        """() => {
          const h = document.getElementById('hub').shadowRoot.querySelector('.fx-page > *');
          return h.shadowRoot.querySelectorAll('link[rel="stylesheet"]').length;
        }"""
    )
    check("bare fixture really skips tokens link (fixture integrity)", bare_links == 0, str(bare_links))
    page7.wait_for_timeout(600)  # 留出 rAF 自检的帧
    check(
        "bare page does not trigger the display:inline warn",
        not any("满高嵌入契约失效" in w for w in bare_warns),
        "; ".join(bare_warns[:3]),
    )
    page7.close()

    # inline fixture：违反 display:block 契约——壳必须告警且指名元素
    inline_warns: list[str] = []
    inline_errs: list[str] = []
    page8 = browser.new_page(viewport={"width": 1280, "height": 800})
    page8.on(
        "console",
        lambda msg: inline_warns.append(msg.text) if msg.type == "warning" else None,
    )
    page8.on("pageerror", lambda e: inline_errs.append(str(e)))
    page8.goto(base + "/?inline=1&single=1")
    wait_shadow(page8, '[data-stub="inline"]', "inline stub mounts (contract-violating)")
    warned = False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any("满高嵌入契约失效" in w and "inline-stub-page" in w for w in inline_warns):
            warned = True
            break
        page8.wait_for_timeout(150)
    check(
        "inline page triggers the naming console.warn (R1 #2 signal face)",
        warned,
        "; ".join(inline_warns[:3]),
    )
    check("inline page boots without pageerror", not inline_errs, "; ".join(inline_errs[:3]))
    page8.close()

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


# ---- scroll-ownership helpers (FXH R1 #1) -----------------------------------

SCROLL_METRICS_JS = """(stub) => {
  const sr = document.getElementById('hub').shadowRoot;
  if (!sr) return { settled: false };
  const host = sr.querySelector('.fx-page > *');
  const content = sr.querySelector('.fx-content');
  const pageBox = sr.querySelector('.fx-page');
  if (!host || !content || !pageBox || !host.shadowRoot ||
      !host.shadowRoot.querySelector('[data-stub="' + stub + '"]')) {
    return { settled: false };
  }
  const cs = getComputedStyle(host);
  const m = {
    hostName: host.tagName.toLowerCase(),
    hostDisplay: cs.display,
    hostOverflowY: cs.overflowY,
    hostScroll: host.scrollHeight,
    hostClient: host.clientHeight,
    contentScroll: content.scrollHeight,
    contentClient: content.clientHeight,
    pageScroll: pageBox.scrollHeight,
    pageClient: pageBox.clientHeight,
  };
  m.settled = m.hostDisplay === 'block' && m.hostOverflowY === 'auto'
    && m.hostScroll > m.hostClient && m.contentScroll === m.contentClient;
  return m;
}"""


def scroll_probe(page, stub: str, deadline_s: float = 8.0) -> dict:
    """Poll the scroll-ownership metrics until the contract settles.

    契约（FXH 滚动条批，R1 #1）：挂载进来的页面元素是唯一纵向滚动容器，
    壳 .fx-content 永不滚动。轮询到全部谓词成立（tokens <link> 异步加载、
    字体/布局就绪都自然被等掉）；失败时带最后一帧指标返回而非裸超时，
    让 FAIL 自带诊断。回退壳侧布局改动会让 settled 永不成立。
    """
    deadline = time.monotonic() + deadline_s
    metrics: dict = {}
    while True:
        metrics = page.evaluate(SCROLL_METRICS_JS, stub)
        if metrics.get("settled"):
            return metrics
        if time.monotonic() >= deadline:
            metrics["settled"] = False
            return metrics
        page.wait_for_timeout(150)


# ---- A1 overscroll helpers（FXH 2026-11-15）---------------------------------

OVERSCROLL_JS = """() => {
  const sr = document.getElementById('hub').shadowRoot;
  if (!sr) return { ready: false };
  const tabs = sr.querySelector('.fx-tabs');
  const shell = sr.querySelector('.fx-shell');
  const host = sr.querySelector('.fx-page > *');
  if (!tabs || !shell) return { ready: false };
  return {
    ready: true,
    tabsOverflowY: getComputedStyle(tabs).overflowY,
    tabsOverscroll: getComputedStyle(tabs).overscrollBehavior,
    shellOverscroll: getComputedStyle(shell).overscrollBehavior,
    hostOverscroll: host ? getComputedStyle(host).overscrollBehavior : null,
  };
}"""


def poll_overscroll(page, deadline_s: float = 8.0) -> dict:
    """Poll computed overscroll styles until tokens.css has loaded and applied.

    就绪判据=tab 条 overscroll 已生效为 none（tokens link 异步加载、布局
    就绪都被等掉）；失败时带最后一帧指标返回，让 FAIL 自带诊断。回退
    壳侧 overscroll 改动会让就绪判据永不成立而超时失败。
    """
    deadline = time.monotonic() + deadline_s
    metrics: dict = {}
    while True:
        metrics = page.evaluate(OVERSCROLL_JS)
        if metrics.get("ready") and metrics.get("tabsOverscroll") == "none":
            return metrics
        if time.monotonic() >= deadline:
            return metrics
        page.wait_for_timeout(150)


def check_scroll_owner(prefix: str, m: dict) -> None:
    """Assert each half of the scroll-ownership contract with detail."""
    check(prefix + ": page element display block", m.get("hostDisplay") == "block", str(m))
    check(prefix + ": page element overflowY auto", m.get("hostOverflowY") == "auto", str(m))
    check(
        prefix + ": page element overflows internally",
        m.get("hostScroll", 0) > m.get("hostClient", 0),
        str(m),
    )
    check(
        prefix + ": shell .fx-content does not scroll",
        m.get("contentScroll") == m.get("contentClient"),
        str(m),
    )
    check(
        prefix + ": shell .fx-page does not overflow",
        m.get("pageScroll") == m.get("pageClient"),
        str(m),
    )


if __name__ == "__main__":
    raise SystemExit(main())
