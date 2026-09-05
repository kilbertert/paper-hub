---
status: accepted
---

# Download Format Preference and Frontend Search-State Restore

paper-hub 的单一下载入口按"PDF 优先"选择合法全文资产：native 候选存在 PDF 时直接下载 PDF；native 候选仅有 XML（Europe PMC JATS）时仍查询 Unpaywall，命中合法 PDF 则下载 PDF，否则回退 XML。XML 不保留 UI 入口——程序化获取者可直接调用来源 API。结果卡片按确定性证据显示格式徽标：native 候选显示具体格式（全文 PDF / 全文 XML），无 native 候选显示中性的"可能可下载"，搜索时不逐篇调用 Unpaywall（徽标保持概率语义，不追求 100% 准确）。搜索状态的返回恢复用 sessionStorage 存 UI 投影（卡片实际渲染字段 + 查询条件），页面加载时恢复搜索视图；收藏/已下载视图不恢复（后端已持久化且常驻按钮可达）。放弃存储 5MB 完整 payload 的方案：投影后配额数学上不可达上限（100 条 × ~500B ≈ 1%），存储/恢复全程静默降级（禁用或异常时行为等同现状），不向用户报错。这样避免了 Europe PMC 论文"下载出 XML 惊喜"与"返回搜索列表消失"两个缺陷，同时不把徽标准确性变成每搜索 N 次 Unpaywall 调用的成本问题；代价是徽标对 Unpaywall-only 论文不精确、跨标签页/关闭浏览器后搜索状态不恢复（会话语义，可接受）。
