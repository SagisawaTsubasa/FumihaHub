/* Stub page: 高内容版 lux 桩 —— R1 #1 布局回归 fixture（link tokens 路径）。
 * 30+ 张卡片保证桌面与窄屏视口下都真实溢出，供滚动归属断言判别（壳
 * .fx-content 零滚动、滚动落页面元素自身）；回退壳侧修复会让
 * dev/test_panel.py 的新增布局断言失败。生产页面由各集成自己的 static/
 * 提供；本文件仅用于 dev harness。 */
window.FUMIHA.kit.defineOnce(
  "tall-stub-page",
  class TallStubPage extends HTMLElement {
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
      k.addTokens(root); // link tokens.css 路径：:host{display:block;height:100%} 由 tokens 提供

      const cards = [];
      for (let i = 1; i <= 30; i++) {
        cards.push(
          k.el("div", { class: "fx-card" },
            k.el("h2", { text: "溢出卡片 " + i }),
            k.el("p", { text: "滚动归属契约的 filler 行——高内容桩必须有真实高度，布局断言才有判别力。" }))
        );
      }
      root.append(
        k.el("div", { class: "fx-body" },
          k.el("div", { class: "fx-card", "data-stub": "tall" },
            k.el("h2", { text: "高内容桩（link tokens 路径）" }),
            k.el("p", { text: "本页共 31 张卡片，稳定超过内容区高度。" })),
          ...cards)
      );
    }

    disconnectedCallback() {}
  }
);
