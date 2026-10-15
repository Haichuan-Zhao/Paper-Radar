# 全文获取、机构权限与版本

论文发现、期刊评级和全文访问是三种独立能力。EasyScholar key 提供评级；
索引/元数据 API key 不自动包含出版社全文授权。机构订阅也可能只覆盖部分
期刊、年份、文章类型或下载方式。skill 不创建订阅、不自动付款。

## 路由顺序

1. 复用来源给出的开放链接，检查出版社 OA、合法仓储、作者接受稿及明确关联
   的预印本。按 DOI/native ID 找副本；近似标题只作线索，不能自动确认身份。
2. 用户配置 Unpaywall 时按 DOI 补查合法 OA 地址；生命科学可另启 Europe PMC。
   保留 license、稿件版本、host type、检索时间。未来 embargo 副本不可列为当前可用。
3. 用户有出版社全文 API 授权且已有可用适配器时，按合同/许可使用该 API。
   部分出版社适配器可优先走此路径；metadata key 不等于全文 entitlement。
   此 skill 的 Python helper **只查公开元数据**，不内置这些付费 API 的下载适配器。
4. 使用用户已有机构订阅：从真实图书馆数据库入口、代理/VPN 或出版社机构登录
   进入，复用原浏览器 profile 和已登录会话。新浏览器未登录不能证明机构无权限。
5. 仍不可读：保留候选及缺口，列出用户已有 PDF、图书馆文献传递/馆际互借、
   作者合法仓储/索取、用户决定购买等选项。发邮件、提交馆际互借、购买均需用户
   对该操作的授权；本 helper 不执行这些动作，也不寻找未经授权的镜像。

优先复用已有登录；用户也可配置自己的账号密码，经宿主的私密本地适配器登录，
见 [institution-login.md](institution-login.md)。OTP、二维码及验证码由用户在
目标浏览器完成。一个批次复用会话，真正过期时统一刷新一次，随后继续剩余论文。
机构配置保存稳定入口、浏览器标识、预期域名和可选凭据来源引用；凭据值独立
保存在用户私有来源，不进入路由配置/运行输出，不导出 cookie 或认证会话。

## 配置

默认复用现有来源链接，不增加远程查询。按用户需要启用补查服务：

```json
{
  "fulltext_access": {
    "unpaywall": {"enabled": true, "email_env": "UNPAYWALL_EMAIL", "email": null},
    "europepmc": {"enabled": false},
    "institution": {"enabled": false, "profile": null, "config_file": null},
    "max_lookups": 60,
    "timeout": 15,
    "pause": 1
  }
}
```

Unpaywall 要求用户自己的联系邮箱，可由环境变量注入或填 email；环境优先。
不要用项目作者/他人的邮箱。邮箱会送给该 API，helper 不写入获取 manifest。
email 缺失时记录 inconclusive，不杜撰联系人。Europe PMC 是可选的领域服务，
不是所有学科的数据库。max_lookups 限制按主题相关性排列的候选数量，并受
assessment.review_limit 限制；最多每篇每个启用服务 1 次，失败不无界重试。

机构路由直接填写在 [用户配置文档](../USER_CONFIG.template.md) 的
fulltext_access.institution.routing，填写真实学校/图书馆/SSO 来源后再启用。
已有命名机构配置可继续通过 profile/config_file 引用；两种入口不可同时设置。
账号输入、浏览器会话复用和适配器协议见 [institution-login.md](institution-login.md)。
doctor 检查配置，不确认浏览器登录或订阅资格。

各 harness 用其原生浏览器/网络/文件工具执行实际阅读。没有浏览器能力的
harness 使用合法 OA/已授权 API/用户文件，并把机构路径保留为 handoff。
不依赖安装 nature-downloader；如用户使用该 downloader，遵循它的明确流程。

## 获取状态与观察

run 自动生成 access/ 的 manifest、汇总、计划和空白观察模板，也把路由放入
内容复核 packet。独立补查不修改历史 candidates 或已有评分：

```bash
python3 radar.py access --run /path/to/run --profile /path/to/my-profile.json \
  --out /path/to/new-access-check
# 宿主实际打开指定页面/文件、填写观察后再合并；模板不能直接当成完成结果
python3 radar.py access --run /path/to/run \
  --observations /path/to/access-observations.completed.jsonl \
  --out /path/to/checked-access
python3 radar.py prepare-review --run /path/to/run \
  --access /path/to/checked-access/access-manifest.jsonl --out /path/to/new-review
python3 radar.py assess --run /path/to/run --reviews /path/to/reviews.completed.jsonl \
  --access /path/to/checked-access/access-manifest.jsonl --out /path/to/new-assessment
```

| 状态 | 依据/下一步 |
|---|---|
| oa_link_found | 索引提供开放链接，尚未确认页面/文件可读；打开核对 |
| readable_copy_verified | 宿主声明已检查可读全文的身份、版本、方法、时间和原文锚点；仍需内容和图表评审 |
| alternative_version_available | 正式论文的可读副本是预印本；另立预印本候选，按具体版本评估 |
| institution_route_available | 有机构入口，登录状态及该文章授权未知 |
| login_required | 实际页面要求登录；复用/刷新指定会话 |
| subscription_required | 实际检查的入口提示没有相应订阅；不代表所有副本都不可读 |
| no_open_copy_found | 声明的公开服务未找到当前开放副本；不是购买结论 |
| lookup_inconclusive | 缺邮箱、元数据 API 错误、超时或不匹配，保持未知 |
| access_blocked / route_not_found | 实际页面被拦截或该路径不存在；与全文 entitlement 不混同 |
| not_checked | 未补查、预算外或缺可查询 DOI；保留已有链接 |

观察模板要求 candidate_id/fingerprint、source、checked_at、retrieval_method、
material_version、identity_verified 和原文 evidence.locator/excerpt。
可用 outcome 为 readable_full_text/login_required/subscription_required/not_found/
blocked/timeout。source 为稳定无凭据 URL，user_file 则为已有文件的绝对路径。
API HTTP 401/403、机器人验证、校园网络不通，只能说明该请求失败；
subscription_required 必须来自实际授权/付费页面的明确提示。
一个入口失败时其他开放副本仍可尝试；manifest 保留该观察而不删除其他路由。
这些是可审计的宿主声明，helper 不独立验证声明真实性，也不下载正文来确认。

HTML 正文可用于阅读；abstract-only 页面不能冒充全文。PDF 保存时核验签名、
非零页数、标题/DOI/版本，排除登录页/错误页，保存来源、许可与 SHA-256；
见 [download-and-zotero.md](download-and-zotero.md)。未知许可不自动禁止合法页面
阅读，也不推定可再分发、训练模型或批量下载，按实际来源条款处理。

## 阅读材料与评分绑定

内容评审使用 **schema_version=5 / content-v4**（Q/M 公式保持不变，新增主张审查门槛）。
旧 review 需要重新 prepare-review，核对材料身份并补做主张审查，不能只改版本数字。

access.full_text=true 只在实际阅读正文时填，并同时提供：

- material_candidate_id：本候选 ID；预印本 native_version 必须与候选具体版本一致。
- material_version：publishedVersion / acceptedVersion / submittedVersion。
- full_text_source 与 identity_evidence_id：全文锚点必须与阅读来源一致，其原文
  必须能对应本候选标题或 DOI；宿主还要检查作者、native ID、页首和版本标识。
- retrieval_method：open_access / institution / publisher_api / user_file。
- verified_at：实际读取检查时间；figure_count 和 figures_inspected：真实主图数量
  及已看图号。读图注不等于看过图像。

正文/图/表锚点默认使用实际 full_text_source。补充材料或图片文件采用不同来源时，
在该证据条目同时填写 material_candidate_id、material_version、native_version，
与本次 access 绑定；不同来源不绑定时不能给正文分。prior_work 必须指向实际打开的
外部已有工作，不能把当前论文对前作的自述当作已读前作。

DOI 工作可基于明确标注的 acceptedVersion 评价，阅读清单显示“接受稿”及来源，
这个分数只对应该材料；不能称已确认正式版图表/结论。若候选显式要求
version=publishedVersion，接受稿不能完成它的评审。已发布工作的
submittedVersion 不供应正式论文内容分；建立独立预印本候选/新复核输入并
保留明确关联，分别阅读评分，最终每个 work_family 至多推荐一个版本。

绑定不成立时正文/图表证据不能用于 Q、M 或条件检查；原摘要仍可用于初判。
全文已获取后，最终 M 还需在实际阅读材料的正文/图表中确认；只引用出版社
摘要不足以证明接受稿这一版本符合需求。
链接、订阅及访问模式不加减 Q/M/S。缺全文质量为 null，不能填 0 或中位数。
assessment-summary.acquisition_queue 按已有匹配证据/主题顺序安排获取，
reading-list 分开列可推荐阅读和待获取全文；待获取项不冒称高质量。

## 接口依据

- [Unpaywall REST API](https://unpaywall.org/api)：DOI v2 查询要求联系邮箱；
  自 2026-09-18 起 search 已退役，本 helper 只使用 DOI endpoint。
- [Unpaywall 数据格式](https://unpaywall.org/data-format)：副本版本、许可和
  oa_locations_embargoed 的语义；API 的 deprecated evidence 字段不是核验凭据。
- [OpenAlex work 文档](https://github.com/ourresearch/openalex-docs/blob/main/api-entities/works/work-object/README.md)：
  locations/best_oa_location 的元数据；保留版本和 license，不把 primary_location 当成保证可读的 PDF。
- [Europe PMC REST API](https://europepmc.org/RestfulWebService) 和
  [开放子集](https://europepmc.org/downloads/openaccess)：只有适用开放子集才提供
  fullTextXML；免费页面可读不等于整个集合可自动批量获取。

付费全文 API/真实机构订阅需在用户环境验证。公开元数据 smoke check、模拟
访问观察和结构校验都不能证明所有数据库、harness 或订阅路线已经打通。
