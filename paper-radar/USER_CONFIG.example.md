# Paper-Radar 用户配置 / User configuration

复制为研究工作区的 USER_CONFIG.md 后编辑，放在 skill 安装目录之外。聊天需求优先，空白可后补。
key/密码为本地明文，宿主或模型可能看到；优先 secret 引用或真实网页登录，不提交 GitHub。

## 1. 使用偏好 / Preferences

| 配置项 / Setting | 我的设置 / Value |
|---|---|
| 输出语言 / Output language | 简体中文 |
| 希望精读篇数 / Reading target | 10 |
| 检索深度 / Search depth | 深入：多来源、扩词、前后向引用追踪和漏检补查 |
| 预印本 / Preprints | 接受，单独标注发表与同行评审状态 |
| 期刊评级 / Journal metrics | 希望使用 EasyScholar；缺 key 时先让我选择补全或本次跳过 |
| 缺项处理 / Missing settings | 每次检索前检查，列明影响，由我选择补全或本次接受限制 |
| 搜索预算 / Search budget | 最多 6 轮实质性工作；更严格的时间/调用与宿主限制优先，未完成就保存部分交付 |
| 协作偏好 / Collaboration | 有真实原生子 agent 且获授权时分工；否则顺序自查并标注 |
| 结果目录 / Results directory | ./paper-radar-results |
| 下载目录 / Download directory | ./paper-radar-downloads |

## 2. EasyScholar 与其他服务 / Keys and services

| 配置项 / Setting | 我的设置 / Value |
|---|---|
| EasyScholar key | |
| EasyScholar secret 引用或环境变量名 / Secret reference or env name | EASYSCHOLAR_SECRET_KEY |
| EasyScholar 自定义数据集偏好 / Custom rating datasets | |
| OpenAlex key（可选）/ Optional key | |
| OpenAlex secret 引用或环境变量名 / Secret reference or env name | OPENALEX_API_KEY |
| 其他文献连接器 / Other scholarly connectors | |
| 本地期刊评级表路径（可选）/ Local journal metric files | |
| OA 查询联系邮箱（可选）/ OA lookup contact email | |

## 3. 学校图书馆 / Institutional library

| 配置项 / Setting | 我的设置 / Value |
|---|---|
| 机构访问 / Institutional access | 关闭；需要时改为开启 |
| 学校名称 / Institution | |
| 图书馆资源入口 / Library URL | |
| 校外访问或 SSO 入口 / Remote access or SSO URL | |
| 允许的图书馆与 SSO 域名 / Allowed domains | |
| 学校邮箱或登录账号 / Library email or account | |
| 密码 secret 引用或环境变量名 / Password secret reference or env name | |
| 密码（可选本地明文，不建议）/ Optional plaintext password | |
| 已登录的浏览器或会话说明 / Existing browser session | |
| 登录方式 / Login method | 优先复用会话，必要时由我在真实网页登录并完成 MFA/验证码 |

## 4. 本次研究任务 / Research task

| 配置项 / Setting | 我的设置 / Value |
|---|---|
| 研究主题 / Topic | |
| 完整原始需求 / Original request | |
| 阅读目的 / Reading purpose | |
| 起始日期 / Start date | |
| 结束日期 / End date | |
| 方法偏好（软偏好）/ Preferred methods | |
| 应用条件 / Context | |
| 必须满足的条件 / Hard constraints | |
| 种子论文、作者或 DOI / Seeds | |
| 限定期刊及 ISSN（可选）/ Journal restrictions | |
| IF/JCR/WoS/CAS/CCF 要求（可选）/ Metric requirements | |

## 5. 评分偏好 / Assessment preferences

| 配置项 / Setting | 我的设置 / Value |
|---|---|
| 质量权重 α / Quality weight | 0.60 |
| 最低 Q / Minimum quality | 70 |
| 最低 M / Minimum fit | 70 |
| 其他评价要求 / Other review preferences | |

## 6. 下载偏好 / Download preferences

| 配置项 / Setting | 我的设置 / Value |
|---|---|
| 正文 / Main paper | 展示结果后，等我明确选择再下载 |
| 补充材料 / Supplementary information | 仅在我另行请求时下载 |
| Zotero 或其他文献库 / Library import | 仅在我另行请求时写入 |

目录相对本配置文件。未给日期时默认最近 90 天；精读篇数不限制候选池。
机构关闭时不用填账号；开启时需要真实入口和单篇权限，账号密码不能替代它们。
只配置不启动检索；保存设置不等于下载选择。更新仅补缺失字段，保留已有值和未知字段。
