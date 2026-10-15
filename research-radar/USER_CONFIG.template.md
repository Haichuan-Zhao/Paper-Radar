# 我的 Research Radar 配置

复制本文件到自己的数据目录，例如 user-data/config.md，填写下面这一份文档。
它可以直接作为 radar.py --profile 的输入；JSON 格式也继续支持。
本模板、隐藏输入脚本、[运行前检查](references/preflight.md) 与深度检索规则都随 skill
分发，安装后每位用户配置自己的副本，不需要开发者的个人配置。

## EasyScholar key 和学校邮箱填在哪里

这是本地配置入口，各 harness 都读取用户自己的文档与凭据，不需要上传到项目服务器。

| 信息 | 填写位置 |
|---|---|
| EasyScholar key | 在下面的隐藏输入命令中输入，保存在自己的 private/api-keys.json；将 JSON 中 easyscholar.credentials_file 从 null 改成 "private/api-keys.json" |
| 学校图书馆邮箱/账号 | 在学校凭据命令的第一个提示中输入；学校使用邮箱登录就填完整邮箱，使用学号就填学号 |
| 学校登录密码 | 在学校凭据命令的第二个提示中输入，同邮箱/账号一起保存在 private/institution-accounts.json |
| 学校与访问入口 | 填在下方 fulltext_access.institution.routing 中的 institution、library_url、login_url、allowed_domains；填好后将 institution.enabled 改为 true |

在用户自己的交互终端中，从 skill 目录运行（替换数据目录路径）：

    python3 scripts/credentials.py configure --service easyscholar --out /path/to/user-data/private/api-keys.json
    python3 scripts/institution_credentials.py configure --profile my-school --out /path/to/user-data/private/institution-accounts.json

输入不会显示在终端，也不通过命令参数或聊天消息传递。两个私有文件是本地明文，
POSIX 权限为 600；可用宿主私密环境变量替代。已有 API key JSON 可放到自己的私有
目录，再填写 credentials_file 路径，格式见 [凭据说明](references/credentials.md)。
仅有学校邮箱不能确定图书馆入口或全文权限；学校 SSO/二次验证仍需真实环境处理。
unpaywall.email_env 是 OA 查询服务的联系邮箱引用，与图书馆登录邮箱用途不同。

## 研究需求

先填写 topic（主题）和 user_prompt（完整原话），以及阅读目的、方法偏好、
时间和评级要求。可以交给 agent 补全英文检索式、概念组和日期；agent 必须
保留 user_prompt，不把方法偏好变成硬性排除。未指定时间时按用户当地日期填写
最近 90 天。queries 和 date.from 补全后才能执行检索。

| 配置 | 如何填写 |
|---|---|
| topic / user_prompt | 研究主题；想找什么、为什么读、希望解决什么问题 |
| requirements | 阅读目的、方法偏好、应用条件；硬约束使用有 id/description 的对象 |
| queries / relevance.required_concepts | 完整英文领域检索式；概念组用 name/terms 表达对象、任务和必要方法 |
| date / count / sources | 起止日期、希望阅读篇数、来源；含 arxiv 表示检索预印本，可换为 biorxiv/medrxiv |
| search | 默认 deep；citation_hops 为引用追踪深度，saturation_rounds 为停止前连续无新增相关论文的扩展轮次；不以 count 限制搜集数量 |
| filters.include_only | 可选 IF 下限、JCR 分区、WoS 索引；null 表示不限制 |
| journal_issns | 可选限刊范围，先核验 ISSN；不要填近似刊名 |
| easyscholar / openalex | 自己的 key 的环境变量名，或 private/api-keys.json 路径；见 [凭据格式](references/credentials.md) |
| fulltext_access | 可选 OA 补查，以及学校真实入口、浏览器和私有凭据文件位置 |
| assessment | 内容质量与匹配的权重/门槛；默认公式和量表见 [评分说明](references/scoring.md) |

下面只保留一个 json 代码块。空字符串和空数组表示待补全。机构访问默认关闭；
启用时填写 routing 内的学校和真实入口，allowed_domains 列出图书馆及实际 SSO 主机。

```json
{
  "topic": "",
  "topic_en": "",
  "user_prompt": "",
  "requirements": {
    "purpose": "",
    "preferred_methods": [],
    "context": "",
    "hard_constraints": []
  },
  "queries": [],
  "relevance": {"mode": "review", "required_concepts": []},
  "date": {"from": "", "to": "today", "basis": "online-first"},
  "count": 10,
  "sources": ["crossref", "openalex", "arxiv"],
  "search": {"mode": "deep", "citation_hops": 2, "saturation_rounds": 2},
  "journal_issns": [],
  "filters": {
    "preprint_venue_policy": "separate",
    "include_only": {
      "min_jif": null,
      "jcr_quartiles": null,
      "wos_indexes": null,
      "peer_reviewed_only": false
    }
  },
  "assessment": {"quality_weight": 0.6, "quality_floor": 70, "match_floor": 70},
  "venue_metrics_files": [],
  "easyscholar": {"enabled": true, "secret_key_env": "EASYSCHOLAR_SECRET_KEY", "credentials_file": null},
  "openalex": {"api_key_env": "OPENALEX_API_KEY", "credentials_file": null},
  "fulltext_access": {
    "unpaywall": {"enabled": false, "email_env": "UNPAYWALL_EMAIL"},
    "europepmc": {"enabled": false},
    "institution": {
      "enabled": false,
      "profile": "my-school",
      "routing": {
        "institution": "",
        "library_url": "",
        "login_url": "",
        "allowed_domains": [],
        "browser": "chrome",
        "browser_profile_label": "Research",
        "credential_login_mode": "user_authorized_ephemeral",
        "secret_storage": "external_secret_reference",
        "credential_source": {
          "username_env": "RR_LIBRARY_USERNAME",
          "password_env": "RR_LIBRARY_PASSWORD",
          "credentials_file": "private/institution-accounts.json"
        }
      }
    }
  }
}
```

私有凭据不随 skill/仓库发布。适配器在用户已授权的登录任务中读取/发送凭据；
二维码/二次验证由用户完成。宿主的适配能力见 [机构登录说明](references/institution-login.md)。

相对路径一律相对于本配置文档所在目录。填好后执行：

    python3 radar.py validate --profile /path/to/user-data/config.md
    python3 radar.py preflight --profile /path/to/user-data/config.md
    python3 radar.py run --profile /path/to/user-data/config.md --out /path/to/user-data/new-run

每次检索前都检查。缺少已启用的 key/账号或其他必要信息时，skill 先说明影响，
由用户选择先补全或接受缺口继续；未选择之前不开始搜集。run 同样会检查并以
退出码 3 暂停。用户已选择继续时，宿主才为本次 run 加 --continue-with-gaps。
离线检查通过不等于远端 key 有效或学校登录成功。

## 两步使用

1. **搜集、评估、展示结果**：默认先多来源、多组检索式、完整分页，再扩词、前后向
   引用追踪和漏检补查；run 生成候选、检索计划/日志模板及评审模板。宿主记录真实
   补查轮次，报告候选数量、覆盖缺口与停止原因；不只找够 count 篇就停止。
   宿主阅读实际全文和图表，
   再执行 assess，交付带固定编号的 reading-list.md、Q/M/S、期刊信息与获取状态。
   无全文时 Q/S 保持待评；为评价打开合法全文，可使用临时缓存，不自动批量保存 PDF。
2. **选择后下载**：阅读结果后回复“下载第 1、3、5 篇”。宿主把这份结果的编号
   映射到明确 DOI/版本，只下载所选正文；需要补充材料或 Zotero 导入时另外说明。
   一次明确选择后直接执行，无需重复确认。select 生成计划，实际获取由宿主执行。

选择命令示例（编号来自同一目录的 reading-list.md）：

    python3 radar.py select --assessment /path/to/user-data/new-run/assessment --numbers 1,3,5 --out /path/to/user-data/chosen-downloads

validate/doctor 不发起登录，也不创建订阅。缺 key、缺评级或缺全文均保留真实缺口。
