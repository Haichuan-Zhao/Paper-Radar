# 期刊评级、EasyScholar 与来源核验

评级是阅读背景和用户明确指定的过滤条件，不直接计入内容质量 Q。
预印本的期刊评级是“不适用”，不是 0 分；peer-reviewed-only 条件仍排除未评审预印本。

## 每位用户的 key

从 USER_CONFIG.md 的 EasyScholar key、secret 引用/环境变量名和数据集偏好取得配置。
引用可用时优先引用；值为空、占位或请求失败时遵循 preflight。
读取和请求须使用宿主允许的私密方式，不回显、不写入日志/结果/公开源码。
配置了 key 不意味着可访问收费论文或所有学术数据库。

本项目既有接口线索为 GET https://www.easyscholar.cc/open/getPublicationRank，
查询字段为 secretKey 和 publicationName。使用前核对当前服务文档/真实响应；
这不是固定 SDK，也不是本次已通过真实 key 测试的保证。
该服务把 key 放在查询参数时，公共 web 搜索/会保留完整 URL 的普通 fetch 不适用。
使用可隐藏凭据和请求 URL 的宿主 secret/HTTP 工具，禁止向其他域转发凭据；
无法安全调用则让用户选择本地导出评级表或跳过本次评级。

同一次检索按已确认的期刊身份复用本次查询结果；缓存保留来源/时间/身份/版次，
失效或冲突必须重核，不能为避免请求而填造数据。用户自定义数据集按原名显示，
不得改名为官方 JCR、CAS 或 WoS 认证。

## 每个指标保留的证据

| 字段 | 要求 |
|---|---|
| identity | 原始刊名、ISSN/eISSN/ISSN-L、关联依据与冲突 |
| value | 来源原始值；未知为 null/待核验，不能估计 IF 或分区 |
| provenance | 服务/用户表/官方来源、可回访位置、检索时间 |
| edition / year | 发布版次与数据年分别保存，未知就说明 |
| category / track | 同版所有学科、CAS 大/小类、会议主会/附属 track |
| verification | 实际核验、来源/用户声明、未核验、冲突；说明依据 |

EasyScholar 响应缺身份/年份时只报告“服务返回的值，身份/版次待核验”。
HTTP 200、当前版权年和新鲜缓存不能证明某年度 JIF。不要把来源的 sci 字段
自动解释为 SCIE，也不要从 IF 推断 WoS 索引。

## 官方核对与严格筛选

- JIF/JCR：依据 [Journal Citation Reports](https://clarivate.com/academia-government/scientific-and-academic-research/research-funding-analytics/journal-citation-reports/)
  或用户合法授权资料，保存版次、数据年和全部学科。同一版次多学科默认严格过滤
  取所列最差分区，除非用户明确选择学科；不得混版取最好值。
- WoS：SCIE/SSCI/ESCI/AHCI 依据 [Master Journal List](https://mjl.clarivate.com/home)
  或授权索引记录，独立于 IF/JCR。
- CAS：依据 [官方分区平台](https://www.fenqubiao.com/) 或可追溯授权导出，
  区分大类与小类。
- CCF：依据 [官方目录](https://www.ccf.org.cn/Academic_Evaluation/By_category/)，
  记录版次、修订与实际 track；不把主会级别授予未核实的 workshop/短文。

本地 CSV/JSON 表可通过配置路径提供，至少包含期刊标识、指标名/值、来源、
版次/数据年和核验依据。用户提供的 verified 字段只是声明，不能替代实际来源检查。
要求“最新”时先核对官方发布依据，不把示例年份写成永久最新。
严格 IF/索引/分区条件未知时进入待核验队列，不能默默通过或改用历史版。
