/* Stub page: lux_balance 占位 —— 验证壳↔页面契约与 cx-* 组件观感。
 * 生产页面由各集成自己的 static/ 提供；本文件仅用于 dev harness。 */
window.FUMIHA.kit.defineOnce(
  "lux-stub-page",
  class LuxStubPage extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._hass = null;
      this._stopPoll = null;
      this._ticks = 0;
    }

    set hass(h) {
      this._hass = h;
      const v = this.shadowRoot.querySelector('[data-metric="hass"]');
      if (v) v.textContent = h ? "已注入" : "无";
    }

    connectedCallback() {
      const k = window.FUMIHA.kit;
      const root = this.shadowRoot;
      root.innerHTML = "";
      k.addTokens(root);

      const t = k.makeT({
        title: { zh: "亮度均衡（桩页面）", en: "Lux Balance (stub)" },
        ping: { zh: "模拟写操作", en: "Fake write" },
      });

      const tick = k.el("span", { class: "v", "data-metric": "ticks", text: "0" });
      const hassState = k.el("span", { class: "v", "data-metric": "hass", text: this._hass ? "已注入" : "无" });

      const pingBtn = k.el("button", {
        class: "cx-btn primary",
        "data-action": "ping",
        onclick: async () => {
          try {
            await k.api(this._hass).post("/api/devstub/ping", {});
            k.ack(root, { ok: true, label: t("ping") });
          } catch (err) {
            k.ack(root, { ok: false, label: t("ping"), reason: err.message });
          }
        },
      }, t("ping"));

      const confirmBtn = k.el("button", {
        class: "cx-btn danger",
        "data-action": "confirm",
        onclick: async () => {
          const yes = await k.confirmDialog(root, {
            title: "确认操作",
            text: "这是一个桩确认对话框。",
            confirmLabel: "执行",
            danger: true,
          });
          k.toast(root, yes ? "已确认" : "已取消");
        },
      }, "确认框");

      root.append(
        k.el("div", { class: "fx-body" },
          k.el("div", { class: "fx-card", "data-stub": "lux" },
            k.el("h2", { text: t("title") }),
            k.el("p", { style: { color: "var(--fx-sub)" }, text: "壳 → 动态 import → 元素挂载链路已通。" }),
            k.el("div", { class: "cx-status" }, pingBtn, confirmBtn)
          ),
          k.el("div", { class: "fx-grid" },
            k.el("div", { class: "cx-metric" }, tick, k.el("span", { class: "l", text: "轮询 tick" })),
            k.el("div", { class: "cx-metric" }, hassState, k.el("span", { class: "l", text: "hass 注入" })),
            k.el("div", { class: "cx-metric" },
              k.el("span", { class: "v", text: "312 lux" }),
              k.el("span", { class: "l", text: "当前照度" }))
          ),
          k.el("div", { class: "fx-card" },
            k.el("h2", { text: "标定曲线（占位）" }),
            k.el("div", { class: "cx-note", text: "生产页将在 P1 渲染真实标定曲线。" }),
            k.el("div", { class: "cx-bar", style: { marginTop: "10px" } },
              k.el("div", { class: "fill", style: { width: "64%" } }))
          )
        )
      );

      this._stopPoll = k.startPolling(() => {
        this._ticks += 1;
        tick.textContent = String(this._ticks);
      }, 5000);
    }

    disconnectedCallback() {
      if (this._stopPoll) this._stopPoll();
      this._stopPoll = null;
    }
  }
);
