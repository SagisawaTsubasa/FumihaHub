/* ==========================================================================
 * Fumiha Hub shell — the single sidebar entry for all Fumiha pages.
 *
 * Directory-driven UI ported from the Codex web shell, trimmed to what an
 * HA panel needs:
 *   - the single route is location.hash (#pn=<page id>); refresh and share
 *     keep the position;
 *   - the directory is polled with the Codex trio: rev gate (unchanged rev
 *     never re-renders tabs), single-flight guard (no request pileup),
 *     hidden-tab skip;
 *   - pages are ES modules served by their own integration and lazy
 *     imported here; a module defines the custom element named by its
 *     descriptor. The shell owns navigation, tokens and loading — pages own
 *     everything else (框架归壳、页留模组).
 *
 * Page module contract (see also registry.py):
 *   window.FUMIHA.kit.defineOnce("lux-balance-page",
 *     class extends HTMLElement { set hass(h) {...} ... });
 * Descriptor: {id, title, icon?, order?, version, module_url, element}.
 * ========================================================================== */

const STATIC_BASE = "/fumiha_hub";
const DIRECTORY_URL = "/api/fumiha_hub/panels";
const POLL_MS = 5000;
const HASH_RE = /pn=([A-Za-z0-9_.-]+)/;

/* Own module URL carries the hub version as ?ver= — reuse it for the kit
 * and tokens so all three release together (WHA-F-052 lesson: every asset
 * must inherit the cache buster). */
const SELF_VER = new URL(import.meta.url).search;

class FumihaHubPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._dir = null;          // last directory payload {dir_rev, panels}
    this._renderedRev = null;  // rev gate: last rev rendered into the tab strip
    this._renderedSel = null;  // rev gate: last selection rendered
    this._sel = null;          // selected page id
    this._pageHost = null;
    this._tabHost = null;
    this._metaHost = null;
    this._lamp = null;
    this._age = null;
    this._rev = null;
    this._content = null;
    this._stopPoll = null;
    this._stopClock = null;
    this._lastOk = 0;
    this._conn = "idle";       // idle | ok | err
    this._pollInFlight = false;
    this._importSeq = 0;       // stale-import race guard
    this._mountedElement = null;
    this._mountedVersions = new Map(); // element name -> version first mounted
    this._onHash = this._onHash.bind(this);
  }

  set hass(value) {
    const first = !this._hass;
    this._hass = value;
    const lang = value && value.language ? value.language : "zh-Hans";
    window.FUMIHA = window.FUMIHA || {};
    window.FUMIHA.lang = String(lang).toLowerCase().startsWith("zh") ? "zh" : "en";
    // HA may inject hass after connect; react immediately so the first
    // directory poll does not wait out the interval (Stockroom lesson).
    if (first && this.isConnected) this._poll();
    if (this._mountedElement) this._mountedElement.hass = value;
  }

  get hass() {
    return this._hass;
  }

  set route(value) {
    // HA path routing is unused; the single route is the hash below.
  }

  connectedCallback() {
    // A hass assignment that landed before custom-element upgrade created an
    // own property shadowing the prototype setter — re-route it through the
    // setter or the shell would never see hass (dead polls, blank shell).
    if (Object.prototype.hasOwnProperty.call(this, "hass")) {
      const early = this.hass;
      delete this.hass;
      this.hass = early;
    }
    const root = this.shadowRoot;
    root.innerHTML = "";
    if (!window.FUMIHA || !window.FUMIHA.kit) {
      this._injectKit(() => this._boot());
      return;
    }
    this._boot();
  }

  disconnectedCallback() {
    // Kill any in-flight import immediately: its seq check would otherwise
    // pass and mount into a detached DOM (FXH-F-001/F-002).
    this._importSeq += 1;
    if (this._stopPoll) this._stopPoll();
    if (this._stopClock) this._stopClock();
    window.removeEventListener("hashchange", this._onHash);
    this._stopPoll = null;
    this._stopClock = null;
  }

  /* ---- boot ------------------------------------------------------------- */

  _injectKit(onReady) {
    const s = document.createElement("script");
    s.src = STATIC_BASE + "/kit.js" + SELF_VER;
    s.onload = () => {
      // The element may have been detached while the script was loading —
      // booting then would start timers and a window listener on a node
      // nobody can see (FXH-F-002). Reconnect re-runs connectedCallback,
      // which finds the kit ready and boots properly.
      if (this.isConnected) onReady();
    };
    s.onerror = () => {
      // 错误必须响: without the kit we cannot render a proper error card —
      // fall back to a bare shadow message.
      this.shadowRoot.innerHTML =
        '<div style="font:13px sans-serif;padding:24px;color:#c62828">' +
        "文羽面板加载失败：kit.js 无法加载（" + s.src + "）</div>";
    };
    document.head.appendChild(s);
  }

  _boot() {
    const kit = window.FUMIHA.kit;
    // Idempotent: a reconnect after kit-assisted boot must not stack a
    // second set of timers (FXH-F-002).
    if (this._stopPoll) this._stopPoll();
    if (this._stopClock) this._stopClock();
    window.removeEventListener("hashchange", this._onHash);

    const root = this.shadowRoot;
    root.innerHTML = "";
    // Pages read this when linking the stylesheet: all three shell assets
    // release together under the same ?ver= cache buster (FXH-F-004,
    // WHA-F-052 lesson).
    window.FUMIHA.tokensHref = STATIC_BASE + "/tokens.css" + SELF_VER;
    kit.addTokens(root);

    // Reset render-gate state: reconnect reuses the same element instance,
    // and stale gates would suppress the rebuild into the fresh DOM
    // (FXH-F-001 — the Stockroom "empty shell after reconnect" lesson).
    this._dir = null;
    this._renderedRev = null;
    this._renderedSel = null;
    this._sel = null;
    this._unmount();

    this._lamp = kit.el("span", { class: "fx-lamp", title: "连接状态" });
    this._age = kit.el("span", { text: "—" });
    this._rev = kit.el("span", { text: "" });
    this._metaHost = kit.el("div", { class: "fx-meta" }, this._lamp, this._age, this._rev);
    const topbar = kit.el(
      "header",
      { class: "fx-topbar" },
      kit.el("h1", { text: "文羽面板" }),
      this._metaHost
    );

    this._tabHost = kit.el("nav", { class: "fx-tabs", role: "tablist", "aria-label": "页面" });
    this._content = kit.el("div", { class: "fx-content", role: "tabpanel", "aria-label": "页面内容" });
    this._pageHost = kit.el("div", { class: "fx-page" });
    this._content.appendChild(this._pageHost);

    root.append(
      kit.el("div", { class: "fx-shell" }, topbar, this._tabHost, this._content)
    );

    window.addEventListener("hashchange", this._onHash);
    this._stopPoll = kit.startPolling(() => this._poll(), POLL_MS);
    this._stopClock = kit.startPolling(() => this._renderAge(), 1000);
    // Zero panels + no hash never reaches _select via _ensureSelection
    // (wanted === first === null): render the empty-state card up front so
    // the content area is never blank (FXH-F-019). The first poll replaces
    // it once a directory arrives.
    if (this._sel === null) this._mount();
    this._poll();
  }

  /* ---- directory --------------------------------------------------------- */

  async _poll() {
    // set hass may run before kit.js finished loading and it seeds an empty
    // window.FUMIHA — guard on the kit itself, not just the namespace.
    if (
      this._pollInFlight ||
      !this._hass ||
      !window.FUMIHA ||
      !window.FUMIHA.kit ||
      !this.isConnected // align with the WHA panel: never poll while detached
    ) {
      return;
    }
    this._pollInFlight = true;
    const kit = window.FUMIHA.kit;
    try {
      const dir = await kit.api(this._hass).get(DIRECTORY_URL);
      // Shape-check before trusting the payload: a 200 with a non-JSON body
      // (reverse proxy interference) or a missing field must land in the
      // error path, never silently degrade to an empty directory with a
      // green lamp (FXH-F-005).
      if (
        !dir ||
        typeof dir !== "object" ||
        typeof dir.dir_rev !== "number" ||
        !Array.isArray(dir.panels)
      ) {
        throw new Error("目录响应格式非法（缺 dir_rev/panels）");
      }
      this._conn = "ok";
      this._lastOk = Date.now();
      const revChanged = !this._dir || dir.dir_rev !== this._dir.dir_rev;
      this._dir = dir;
      if (revChanged) {
        this._renderTabs();
        this._ensureSelection();
      }
      this._renderMeta();
    } catch (err) {
      this._conn = "err";
      this._renderMeta();
      console.error("[fumiha-hub] directory poll failed:", err);
    } finally {
      this._pollInFlight = false;
    }
  }

  _renderMeta() {
    if (!this._lamp) return;
    this._lamp.className =
      "fx-lamp " + (this._conn === "ok" ? "ok" : this._conn === "err" ? "err breath" : "");
    this._lamp.title =
      this._conn === "ok" ? "目录正常" : this._conn === "err" ? "目录不可达" : "未连接";
    if (this._conn === "ok" && this._lastOk) {
      const s = Math.max(0, Math.round((Date.now() - this._lastOk) / 1000));
      this._age.textContent = s + "s前";
    } else if (this._conn !== "ok") {
      this._age.textContent = "—";
    }
    this._rev.textContent = this._dir ? "r" + this._dir.dir_rev : "";
  }

  _renderAge() {
    if (this._conn === "ok" && this._lastOk) this._renderMeta();
  }

  _renderTabs() {
    if (!this._tabHost || !this._dir) return;
    const kit = window.FUMIHA.kit;
    // Gate on both rev and selection: a pure re-select must still update
    // aria-selected even when the directory rev is unchanged.
    if (this._renderedRev === this._dir.dir_rev && this._renderedSel === this._sel) return;
    this._renderedRev = this._dir.dir_rev;
    this._renderedSel = this._sel;
    this._tabHost.replaceChildren();
    const panels = this._dir.panels;
    if (!panels.length) {
      this._tabHost.append(
        kit.el("span", {
          class: "fx-empty",
          style: { padding: "6px 12px" },
          text: "尚无页面注册",
        })
      );
      return;
    }
    for (const p of panels) {
      const badgeText = String(p.id).split(".")[0];
      this._tabHost.append(
        kit.el(
          "button",
          {
            class: "fx-tab",
            role: "tab",
            "aria-selected": p.id === this._sel ? "true" : "false",
            "data-page-id": p.id,
            onclick: () => { location.hash = "pn=" + p.id; },
          },
          kit.el("span", { class: "fx-badge", text: badgeText }),
          String(p.title)
        )
      );
    }
  }

  _selectedFromHash() {
    const m = HASH_RE.exec(location.hash || "");
    return m ? m[1] : null;
  }

  _ensureSelection() {
    if (!this._dir) return;
    const panels = this._dir.panels;
    const wanted = this._selectedFromHash();
    if (wanted && panels.some((p) => p.id === wanted)) {
      this._select(wanted);
      return;
    }
    // Unknown or missing deep link: fall back to the first tab and make the
    // URL shareable. A same-value hash write never fires hashchange.
    const first = panels.length ? panels[0].id : null;
    if (wanted !== first) {
      if (first) location.hash = "pn=" + first;
      else if (wanted) this._select(null);
    }
  }

  _onHash() {
    if (!this._dir) return; // first poll will route
    this._ensureSelection();
  }

  _select(pageId) {
    // null is a real state (zero panels registered): it must still mount so
    // the empty-state card renders instead of a blank content area
    // (FXH-F-007).
    if (this._sel === pageId && pageId !== null) return;
    this._sel = pageId;
    this._renderTabs(); // update aria-selected
    this._mount();
  }

  /* ---- page mounting ------------------------------------------------------ */

  async _mount() {
    const kit = window.FUMIHA.kit;
    const seq = ++this._importSeq;
    this._unmount();

    const page = this._sel && this._dir
      ? this._dir.panels.find((p) => p.id === this._sel)
      : null;
    if (!page) {
      this._pageHost.replaceChildren(
        kit.el("div", {
          class: "fx-empty",
          text: "尚无页面注册 — 安装并配置带面板的集成后自动出现",
        })
      );
      return;
    }

    this._pageHost.replaceChildren(
      kit.el("div", { class: "fx-empty", text: "加载 " + page.title + " …" })
    );

    try {
      await import(page.module_url);
      if (seq !== this._importSeq) return; // a newer mount took over
      if (!customElements.get(page.element)) {
        throw new Error("模块未注册元素 <" + page.element + ">");
      }
    } catch (err) {
      if (seq !== this._importSeq) return;
      console.error("[fumiha-hub] page import failed:", page.module_url, err);
      this._pageHost.replaceChildren(
        kit.el("div", { class: "fx-body" },
          kit.errorCard(String(err && err.message ? err.message : err), () => this._mount())
        )
      );
      return;
    }

    // Same element name under a different module version (deploy while the
    // tab is open): customElements cannot re-define, so a hard refresh is
    // the only correct recovery — surface it instead of running stale code.
    const mountedAt = this._mountedVersions.get(page.element);
    if (mountedAt && mountedAt !== page.version) {
      this._pageHost.replaceChildren(
        kit.el("div", { class: "fx-body" },
          kit.errorCard(
            "页面已从 " + mountedAt + " 更新到 " + page.version + "，需要刷新浏览器后生效。",
            () => location.reload(),
            "刷新"
          )
        )
      );
      return;
    }

    const pageEl = document.createElement(page.element);
    pageEl.hass = this._hass;
    this._mountedElement = pageEl;
    this._mountedVersions.set(page.element, page.version);
    this._pageHost.replaceChildren(pageEl);
  }

  _unmount() {
    this._mountedElement = null;
    if (this._pageHost) this._pageHost.replaceChildren();
  }
}

customElements.define("fumiha-hub-panel", FumihaHubPanel);
