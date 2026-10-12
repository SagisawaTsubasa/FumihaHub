/* Stub page: auto_night_light 占位 —— 状态机 chips + 表格观感样板。
 * 生产页面由集成自己的 static/ 提供；本文件仅用于 dev harness。 */
window.FUMIHA.kit.defineOnce(
  "anl-stub-page",
  class AnlStubPage extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._hass = null;
    }

    set hass(h) {
      this._hass = h;
    }

    connectedCallback() {
      const k = window.FUMIHA.kit;
      const root = this.shadowRoot;
      root.innerHTML = "";
      k.addTokens(root);
      root.append(
        k.el("div", { class: "fx-body" },
          k.el("div", { class: "fx-card", "data-stub": "anl" },
            k.el("h2", { text: "夜灯助手（桩页面）" }),
            k.el("div", { class: "cx-status" },
              k.el("span", { class: "cx-chip tone-ok" },
                k.el("span", { class: "fx-lamp ok" }), "夜间 22:00–06:30"),
              k.el("button", {
                class: "cx-btn primary",
                "data-action": "trigger",
                onclick: () => k.ack(root, { ok: true, label: "立即触发" }),
              }, "立即触发")
            )
          ),
          k.el("div", { class: "fx-grid" },
            k.el("div", { class: "fx-card" },
              k.el("h2", { text: "卧室灯" }),
              k.el("div", { class: "cx-status" },
                k.el("span", { class: "cx-chip tone-ok" },
                  k.el("span", { class: "fx-lamp ok breath" }), "VERIFIED"),
                k.el("span", { class: "cx-chip", text: "12%" }))),
            k.el("div", { class: "fx-card" },
              k.el("h2", { text: "走廊灯" }),
              k.el("div", { class: "cx-status" },
                k.el("span", { class: "cx-chip tone-err" },
                  k.el("span", { class: "fx-lamp err" }), "MISMATCH"),
                k.el("button", { class: "cx-btn danger" }, "重校")))
          ),
          k.el("div", { class: "fx-card" },
            k.el("h2", { text: "锚点时刻表" }),
            k.el("table", { class: "cx-table" },
              k.el("thead", {}, k.el("tr", {},
                k.el("th", { text: "时刻" }), k.el("th", { text: "类型" }),
                k.el("th", { text: "过渡带" }), k.el("th", { class: "num", text: "目标亮度" }))),
              k.el("tbody", {},
                k.el("tr", {}, k.el("td", { class: "num", text: "06:30" }),
                  k.el("td", { text: "日出锚点" }), k.el("td", { class: "num", text: "30min" }),
                  k.el("td", { class: "num", text: "80%" })),
                k.el("tr", {}, k.el("td", { class: "num", text: "22:00" }),
                  k.el("td", { text: "夜间锚点" }), k.el("td", { class: "num", text: "30min" }),
                  k.el("td", { class: "num", text: "12%" }))))
          )
        )
      );
    }

    disconnectedCallback() {}
  }
);
