# Fumiha Hub 文羽面板

所有 Fumiha 系列 Home Assistant 集成的**共享侧边栏壳**——框架归壳、页留模组：壳负责导航、设计令牌与页面加载，各集成自带页面模块并注册进壳，侧边栏只占一个入口。架构参考环世界 FumihaCodex 的 Web 宿主（目录驱动 UI / rev 门 / 单一路由 / provider 徽标）。

> 语言说明：面板 UI 文案以中文为主（作者单语运营）；集成配置流提供 en/zh-Hans 两份翻译，en 为英文文案。

## 安装（HACS）

1. HACS → 自定义存储库 → 仓库 `SagisawaTsubasa/FumihaHub`，类别 `integration`
2. 安装后重启 HA，添加集成「Fumiha Hub 文羽面板」（单全局条目）
3. 侧边栏出现「文羽面板」

## 页面接入（集成开发者）

集成**不 import** 本包，契约只有两个字符串常量 + 一个 dict（见
`custom_components/fumiha_hub/registry.py` 模块文档）：

```python
# async_setup_entry 里（hub 在或不在都安全）：
registry = hass.data.setdefault("fumiha_hub_registry", {})
registry["<provider>.<page>"] = {
    "id": "<provider>.<page>",          # 首段 = 页签 provider 徽标
    "title": "页面标题",
    "icon": "mdi:...",                  # 预留
    "order": 10,                        # 越小越靠前
    "version": "<你的 manifest 版本>",   # module_url 缓存戳
    "module_url": "/<domain>/page.js?ver=<版本>",  # 集成自己的静态路径
    "element": "<provider>-page",       # 模块定义的自定义元素名
}
hass.bus.async_fire("fumiha_hub_page_changed", {"id": "...", "action": "register"})

# async_unload_entry 里：
registry.pop("<provider>.<page>", None)
hass.bus.async_fire("fumiha_hub_page_changed", {"id": "...", "action": "unregister"})
```

页面模块（ES module，经壳 `import()` 动态加载）：

```js
window.FUMIHA.kit.defineOnce("<provider>-page",
  class extends HTMLElement {
    set hass(h) { ... }          // 壳会持续转发 hass
    connectedCallback() { ... }  // window.FUMIHA.kit.addTokens(this.shadowRoot)
    disconnectedCallback() { ... } // 停掉 startPolling 的定时器
  });
```

壳未安装时上述代码照常执行（dict 无人读取而已）——集成可据此检测
`"fumiha_hub_registry" in hass.data` 决定是否回落注册自己的独立面板。

## 开发

```bash
python tests/smoke.py        # L1：stub HA 树冒烟（无需安装 HA）
python dev/serve.py          # L2/L3：http://127.0.0.1:8770 离线壳（mockHass）
python dev/test_panel.py     # L2：Playwright 冒烟 + dev/shots/ 截图（需 playwright）
```

`mockup/shell.html` 双击可开，静态检查壳观感（真 tokens.css）。

## 路线

- P0 壳骨架（本版）
- P1 lux_balance 页 / P2 auto_night_light 页 / P3 Stockroom 迁入 / P4 WHA 迁入
