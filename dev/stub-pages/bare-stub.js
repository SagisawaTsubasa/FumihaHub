/* Stub page: bare 桩 —— R1 #1/#2 fixture，模拟 stockroom/WHA 形态：
 * 不 link hub tokens.css、不用 FUMIHA kit，自带 :host{display:block;height:100%}
 * （页面半边契约）。验证壳侧 inline 满高契约在「无 tokens」路径同样生效。
 * 生产页面对应物 = Stockroom / WHA 自带样式的面板；本文件仅用于 dev harness。 */
window.FUMIHA.kit.defineOnce(
  "bare-stub-page",
  class BareStubPage extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._hass = null;
    }

    set hass(h) {
      this._hass = h;
    }

    connectedCallback() {
      const root = this.shadowRoot;
      root.innerHTML = "";
      // 刻意不走 kit.addTokens：bare 路径的全部 host 样式由页面自带。契约要求
      // :host{display:block}——缺了它 inline 满高契约静默失效（FXH R1 #2）。
      const style = document.createElement("style");
      style.textContent =
        ":host{display:block;height:100%}" +
        ".wrap{padding:16px;font:13px sans-serif}" +
        ".blk{height:60px;margin-bottom:12px;background:#d9dee5;border-radius:8px}";
      const wrap = document.createElement("div");
      wrap.className = "wrap";
      const marker = document.createElement("div");
      marker.setAttribute("data-stub", "bare");
      marker.textContent = "bare 桩（不 link tokens，自带 :host 契约）";
      wrap.append(marker);
      for (let i = 1; i <= 30; i++) {
        const blk = document.createElement("div");
        blk.className = "blk";
        wrap.append(blk);
      }
      root.append(style, wrap);
    }

    disconnectedCallback() {}
  }
);
