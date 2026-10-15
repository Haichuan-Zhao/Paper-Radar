# 宿主选源与接口入口

选择当前真正存在的工具：文献连接器优先提供结构化元数据；网页搜索适合发现线索，
出版社/原始资料用于核验；浏览器用于交互页面与已授权机构会话。
没有连接器时可用宿主 fetch/HTTP/终端网络工具读取公开接口，但无需构建运行程序。
接口、认证和额度会变；首次使用或失败时查官方文档，不照搬旧字段或声称始终免费。

| 来源 | 适用 | 官方入口与关键注意 |
|---|---|---|
| Crossref | 期刊/会议 DOI、身份与日期、参考文献元数据 | [REST 文档](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)；works 查询、精确 DOI 查找、journals/ISSN；[分页说明](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/) |
| OpenAlex | 跨学科发现、来源关系与引用追踪 | [官方帮助](https://help.openalex.org/)；通过已配置连接器或当前 API，检查 key、分页和额度要求 |
| arXiv | 预印本、原始版本与发表关系 | [API 手册](https://info.arxiv.org/help/api/user-manual.html)；网页或 API 查询，保留原生 ID 和 vN |
| bioRxiv/medRxiv | 相关生命/医学方向预印本 | [API 文档](https://api.biorxiv.org/)；details 是预印本记录，pubs 是发表关系，不混用 |
| 出版社/领域索引 | DOI 原始页面、全文、领域覆盖与更正 | 由研究主题和宿主已连接资源决定；实际访问后记录，不能宣称固定支持所有付费库 |
| EasyScholar | 期刊/会议评级与用户自定义数据集 | [服务主页](https://www.easyscholar.cc/)；使用用户 key，见 [评级协议](journal-metrics.md) |

Crossref 与 OpenAlex 的普通全文词检索不可假定支持同一套 Boolean 语法。
按各自文档使用参数，把多个概念的实际相关性留给内容检查，不用 API 命中作为语义证明。

## 分页与响应

- Crossref 常见入口为 https://api.crossref.org/works，精确 DOI 使用 /works/{doi}。
  使用公开文档规定的日期过滤、rows 与 cursor；初次 cursor=*，后续使用本次返回值。
  检查页面内容/短页/当前响应规则，防止过期、重复游标和空页被误报为完成。
- OpenAlex 依据本次官方说明设置 works 搜索/过滤/分页和认证。
  缺 key、无额度或功能受限时停止该分支并记录缺口；不伪造翻页结果。
- arXiv 使用网页或 https://export.arxiv.org/api/query，区分 start/max_results
  与真实条目数量，遵守服务的速率规则。原始提交、更新时间和对应版本日期分开。
- bioRxiv/medRxiv details 可按时间段分批获取，再依据实际标题/摘要筛选；
  它不是任意全文关键词搜索接口。需要分页，保留每个原生 DOI 的版本和日期。
- Respect Retry-After and service limits. 认证失败、429、超时或格式异常进行有限且合适的
  重试；持续失败记录 partial，切换来源不抹去该缺口。成功响应也不证明元数据正确。

HTTP 请求先正确编码用户术语，不能把任意配置文字直接拼成可执行 shell。
没有私密请求能力时，不把用户 key 写进公共浏览器搜索或可回显的调用参数。
只有用户选择所需文件后才进行归档下载，元数据查询不等同于获取全文。
