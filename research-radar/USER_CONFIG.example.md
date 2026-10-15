# Research Radar 用户配置 / User configuration

首次使用时，让 agent 将本文件复制为研究工作目录中的 USER_CONFIG.md，再直接编辑。
也可以把任意位置的配置文件路径告诉 agent。所有表格都可用自然语言填写，中英文均可。
留空表示尚未设置；不需要填写 JSON、检索式或运行命令。
只做安装/配置不代表已经请求检索。

本文件用于个人本地配置。不要提交填写后的副本到 GitHub，也不要粘贴私密值到聊天。
直接填写的 key/密码是明文，读取文件的宿主或模型可能看到它们；优先使用宿主 secret
引用或环境变量名。学校密码优先在真实登录页由用户输入。agent 不回显任何私密值。

## 1. 使用偏好 / Preferences

| 配置项 / Setting | 我的设置 / Value |
|---|---|
| 输出语言 / Output language | 简体中文 |
| 希望精读篇数 / Reading target | 10 |
| 检索深度 / Search depth | 深入：多来源、扩词、前后向引用追踪和漏检补查 |
| 预印本 / Preprints | 接受，单独标注发表与同行评审状态 |
| 期刊评级 / Journal metrics | 希望使用 EasyScholar；缺 key 时先让我选择补全或本次跳过 |
| 缺项处理 / Missing settings | 每次检索前检查，列明影响，由我选择补全或本次接受限制 |
| 搜索预算 / Search budget | 未指定；agent 按任务安排并如实报告限制 |
| 结果目录 / Results directory | ./research-radar-results |
| 下载目录 / Download directory | ./research-radar-downloads |

精读篇数只影响推荐清单长度，不限制检索数量。目录相对本配置文件所在目录。

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

key 可直接填在对应行，也可只填写私密引用；二者都存在时以可用的私密引用为先，
不要把占位文字当作有效 key。API 是否可用以本次实际响应为准。
EasyScholar 提供期刊评级，不授予收费论文权限；OA 联系邮箱也不是学校登录账号。
未启用的其他服务不必补全。

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

账号请填写学校实际使用的邮箱、学号或其他用户名。只给账号密码不能确定学校入口
或订阅权限；agent 会检查真实页面和文章权限。宿主没有安全私密输入能力时由用户登录。

## 4. 本次研究任务 / Research task

可以留空，在聊天中提出本次问题；聊天中的明确要求优先于这里保存的偏好。

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

没有日期要求时，agent 使用当地日期向前 90 天并说明。严格评级条件需要实际核验，
无法核验的候选会标记待核验；不要把方法偏好写成必须条件，除非确实要排除其他方法。

## 5. 评分偏好 / Assessment preferences

| 配置项 / Setting | 我的设置 / Value |
|---|---|
| 质量权重 α / Quality weight | 0.60 |
| 最低 Q / Minimum quality | 70 |
| 最低 M / Minimum fit | 70 |
| 其他评价要求 / Other review preferences | |

默认 S = Q^α × M^(1−α)。内容维度和证据门槛见 skill 的评分协议；
改变权重不能绕过未决主张、已确认核心缺陷或证据缺失。

## 6. 下载偏好 / Download preferences

| 配置项 / Setting | 我的设置 / Value |
|---|---|
| 正文 / Main paper | 展示结果后，等我明确选择再下载 |
| 补充材料 / Supplementary information | 仅在我另行请求时下载 |
| Zotero 或其他文献库 / Library import | 仅在我另行请求时写入 |

保存的目录、账号、评分偏好或“希望阅读 10 篇”都不等于下载选择。
