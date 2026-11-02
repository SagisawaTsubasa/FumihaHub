/* Stub page: inline 桩 —— R1 #2 反向 fixture：刻意违反页面接入契约（无任何
 * display 样式 → 自定义元素默认 display:inline），验证壳侧
 * _checkFullHeightContract 的一次性探测会 console.warn 指名本元素。
 * 本文件仅用于 dev harness。 */
window.FUMIHA.kit.defineOnce(
  "inline-stub-page",
  class InlineStubPage extends HTMLElement {
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
      // 刻意不声明 :host{display:block}——本 fixture 的存在意义就是触发
      // 壳的满高契约告警（display 停留在自定义元素默认值 inline）。
      const marker = document.createElement("div");
      marker.setAttribute("data-stub", "inline");
      marker.textContent = "inline 桩（违反 display:block 契约，应触发壳告警）";
      root.append(marker);
    }

    disconnectedCallback() {}
  }
);
