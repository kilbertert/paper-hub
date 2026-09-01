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

    Scenario: 没有开放全文时显示外链
      Given 论文没有可下载的开放全文资产
      When 用户查看论文详情
      Then 页面显示元数据和合法来源链接
      And 服务不提供支付墙绕过或 sci-hub 下载

  Rule: 本地单用户数据可持续使用

    Scenario: 收藏和查看已下载清单
      Given 用户在本地打开 paper-hub
      When 用户收藏论文或完成一次开放全文下载
      Then 收藏和已下载状态在后续请求中仍可见
