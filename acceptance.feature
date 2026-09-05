Feature: 合规开放论文搜索与下载

  Rule: 用户只能看到来源明确且可追溯的论文结果

    Scenario: 按关键词、来源和年份搜索
      Given 六个论文来源已配置且可访问
      When 用户提交关键词、来源多选和年份范围
      Then 页面展示去重后的论文列表
      And 每条结果显示来源、标题、年份和 DOI（若来源提供）

    Scenario: 查看论文摘要
      Given 搜索结果包含一篇论文
      When 用户打开该论文详情
      Then 页面展示论文摘要和 DOI 解析链接

  Rule: 下载只使用合规开放资产

    Scenario: 下载开放全文
      Given 论文存在来源标记为开放的 PDF 或 XML 全文资产
      When 用户请求下载
      Then 服务校验内容类型和文件魔数后返回全文

    Scenario: 同一论文存在多个合法格式时 PDF 优先
      Given 论文的来源原生候选仅有 XML 全文
      And Unpaywall 为其 DOI 提供合法开放 PDF
      When 用户请求下载
      Then 服务返回 PDF 而非 XML
      And 服务仅当原生候选已有 PDF 时跳过 Unpaywall 查询

    Scenario: 原生 XML 无 PDF 可替代时下载 XML
      Given 论文的来源原生候选仅有 XML 全文
      And Unpaywall 未提供该论文的开放 PDF
      When 用户请求下载
      Then 服务返回校验后的 XML 全文

    Scenario: 结果卡片显示格式徽标
      Given 搜索结果包含带有原生全文候选的论文
      When 用户查看结果卡片
      Then 卡片显示具体格式徽标（全文 PDF 或全文 XML）
      And 无原生候选的论文显示中性提示（可能可下载）
      And 搜索时不为徽标逐篇调用 Unpaywall

    Scenario: 没有开放全文时显示外链
      Given 论文没有可下载的开放全文资产
      When 用户查看论文详情
      Then 页面显示元数据和合法来源链接
      And 服务不提供支付墙绕过或 sci-hub 下载

    Scenario: 浏览器下载不可用时显示友好提示
      Given 论文没有可下载的开放全文资产
      And 用户从浏览器点击下载链接 (Accept: text/html)
      When 下载请求返回失败
      Then 浏览器显示包含中文原因的提示页
      And 提示页提供返回搜索入口
      And API 调用方 (Accept: application/json) 仍收到原 JSON 契约

  Rule: 搜索状态在会话内可恢复

    Scenario: 返回搜索页恢复离开前状态
      Given 用户完成一次搜索并看到结果列表
      When 用户离开搜索页再返回
      Then 关键词、来源勾选、年份范围、仅开放获取勾选和结果列表恢复如离开时
      And 收藏/已下载视图不自动恢复

    Scenario: 状态存储不可用时静默降级
      Given 浏览器禁用 sessionStorage 或存储损坏
      When 用户重新打开搜索页
      Then 页面按无历史状态加载且不报错

  Rule: 本地单用户数据可持续使用

    Scenario: 收藏和查看已下载清单
      Given 用户在本地打开 paper-hub
      When 用户收藏论文或完成一次开放全文下载
      Then 收藏和已下载状态在后续请求中仍可见

  Rule: 检索结果优先保证主题相关性

    Scenario: 中文复合查询扩展为客服意图
      Given 查询扩展生成器返回固定的客服领域中英概念
      When 用户搜索“AI客服”
      Then 返回结果按精确短语、标题、摘要和关键词命中顺序排序
      And 每条前十结果至少命中一个客服意图概念
      And 结果包含命中字段和命中词
      And 只命中“AI”或“artificial intelligence”的论文不会进入前十

    Scenario: 查询扩展生成失败时保持精度门槛
      Given 查询扩展生成器超时或返回非法结果
      When 用户提交搜索
      Then 服务回退到原始查询
      And 回退结果仍经过相同的相关性门槛
      And 服务不使用未经门槛过滤的宽泛结果补足数量

    Scenario: 检索规则升级后不复用旧质量缓存
      Given 搜索缓存由旧的相关性规则版本创建
      When 新规则版本执行同一查询
      Then 服务重新检索或使用新规则版本的缓存
      And 旧规则结果不会直接返回
