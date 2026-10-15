# Research Radar

[English](README.md) | 简体中文

**让 agent 深入搜集文献、依据证据评价，再获取用户选择的论文。**

将 skill 安装到 **Claude Code、Codex 等支持 Agent Skills 的 harness**，
编辑一份个人 Markdown 配置文件，然后直接提出研究需求。agent 使用宿主已有的搜索、
浏览器、文献连接器、阅读与文件工具完成操作。
**使用 skill 无需 Python、Node.js、安装依赖或运行 CLI。**

Research Radar 分开评估**论文内容质量 Q** 与**原始需求匹配度 M**。
期刊评级提供背景与可选过滤，内容评价依据方法、结果、主张、图表及其局限。

## 两步流程

| 阶段 | agent 执行 | 用户得到 |
|---|---|---|
| 1. 搜集与评估 | 检查配置，多来源检索、扩词和引用追踪，核验身份，阅读可用证据并审查主张 | 带固定编号的结果、Q/M/S 或待评、期刊信息、匹配理由、局限、证据与获取状态 |
| 2. 选择后获取 | 将用户选择映射到这份清单，只下载指定论文 | 经过核验的文件与逐篇结果 |

第一步可打开合法全文并使用临时阅读缓存，不自动归档整批 PDF。
agent 会等待“下载第 1、3 篇”这样的明确选择。补充材料和文献库写入需另行请求。

## 安装一次

将完整 [research-radar/](research-radar/) 文件夹放入宿主的 skill 目录：

| 宿主 | 个人安装 | 项目安装 | 调用 |
|---|---|---|---|
| Claude Code | ~/.claude/skills/research-radar/ | .claude/skills/research-radar/ | /research-radar |
| Codex | ~/.agents/skills/research-radar/ | .agents/skills/research-radar/ | $research-radar |

路径核对自 2026-10-15 的
[Claude Code 官方文档](https://code.claude.com/docs/en/skills) 和
[Codex 官方文档](https://learn.chatgpt.com/docs/build-skills)。
旧版本、受管或云环境以实际产品说明为准。其他宿主可读取
[SKILL.md](research-radar/SKILL.md) 及其相对资源。
详见 [部署说明](research-radar/references/deployment.md)。

无需固定 MCP、额外模型 API key 或其他 skill。skill 组织宿主已有能力，
不会自动给 harness 新增工具或权限。

## 直接编辑 USER_CONFIG.md

首次对 agent 说：

> 使用 Research Radar，帮我建立用户配置。

agent 会将 [USER_CONFIG.example.md](research-radar/USER_CONFIG.example.md)
复制为**当前研究工作目录的 USER_CONFIG.md**，不覆盖已有文件，并给出可打开路径。
用户直接编辑普通 Markdown 表格，也可以指定另一个位置的配置副本。
无需编写 JSON 或检索式。

| 配置部分 | 可以填写的内容 |
|---|---|
| 使用偏好 | 输出语言、希望精读篇数、预印本、搜索预算与结果目录 |
| key 与服务 | 自己的 EasyScholar key 或私密引用，可选 OpenAlex key、本地评级表与 OA 联系邮箱 |
| 学校图书馆 | 学校名称、真实图书馆/SSO 入口、允许域名、邮箱/账号、凭据引用和浏览器会话 |
| 本次研究任务 | 完整原始需求、阅读目的、日期、软偏好、硬约束与种子论文 |
| 评分与下载 | 质量权重/门槛、保存目录、补充材料与文献库导入偏好 |

聊天中的明确任务要求优先于保存的任务偏好。agent 自己展开学术术语、概念组与检索式，
不要求用户设计 API 请求。

key 可直接填在本地文档，也可填写宿主 secret 引用或环境变量名。
**直接填写的 key/密码是明文，读取文件的宿主或模型可能看到它们。**
学校密码优先使用私密引用或在真实网页登录。填写后的配置不要提交 GitHub。
本仓库忽略 USER_CONFIG.md 和本地结果；公开示例保持空白，无需项目服务器或上传表单。

**每次检索前** agent 检查已启用服务及真实能力。有缺项时先说明影响，
由用户选择补全后开始，或明确接受本次限制再继续。凭据存在、真实有效、登录成功、
文章订阅权限分别判断。

## 直接对 agent 提需求

Claude Code 使用 /research-radar，Codex 使用 $research-radar，例如：

> 使用 Research Radar，读取我的 USER_CONFIG.md。在我指定的时间范围内，深入查找
> 与原始研究问题匹配的论文，核验论文和期刊信息，依据实际可读全文评价。
> 先展示带编号、质量、匹配度、局限和获取状态的结果，等我选择后再下载。

看过清单后：

> 下载这份清单中的第 1、3、5 篇。

两步均由 agent 在 harness 内执行，没有需要用户另行运行的研究程序。

## 检索与证据

- 根据主题与实际工具选择 Crossref、OpenAlex、arXiv、bioRxiv/medRxiv、领域索引
  和出版社。完整处理实际分页，扩词并前后向追踪引用（默认两跳）。
  希望精读的篇数不限制候选搜集数量。
- 核对 DOI/原生 ID、日期依据、ISSN/ISSN-L、发表状态与真实版本；
  模糊刊名不能直接关联评级。
- 使用每位用户自己的 EasyScholar 数据或本地表，保留 IF/JCR/WoS/CAS/CCF/
  自定义评级的来源、版次与年份。IF 不证明 WoS 收录。
- 阅读实际全文并查看相关图表。只有摘要时保留质量待评，获取困难不降低内容分。
- 使用随包协议和模板保存检索日志、证据锚点、逐篇评审和固定编号目录。

详见 [深入检索](research-radar/references/discovery-and-evidence.md)、
[期刊评级](research-radar/references/journal-metrics.md) 和
[产物协议](research-radar/references/outputs.md)。

## 质量、匹配与主张边界

默认 **S = Q^0.6 × M^0.4**，Q、M 均为 0–100。

| 指标 | 默认维度 |
|---|---|
| Q | 动机 15%、原创性 15%、严谨性 25%、证据 25%、可复核性 10%、图表/论证表达 10% |
| M | 研究问题 45%、方法路径 25%、应用条件 20%、阅读目的 10% |

推荐需要 Q/M ≥ 70、rigor/evidence ≥ 3/5、完整证据审查及用户要求的条件。
作者声望、IF 与图片美观程度不加内容分，预印本缺评级不扣分。

agent 审查核心主张，区分作者报告与评审判断，核对正面和负面评价的原始证据。
核心主张或重大疑点未决时最终 Q/S 待评；需要收窄的主张限制分数与推荐等级，
确认的核心证据失败不能由高综合分掩盖。

这些是**宿主 agent 执行的指令与评审标准**，没有程序评分器强制保证，
不能证明科学结论正确。量表可配置，尚未完成领域准确率/召回率基准验证。
详见 [评分规则](research-radar/references/scoring.md) 和
[质量评审](research-radar/references/quality-evaluation.md)。

## 获取与能力边界

可用 OA、用户文件和授权机构会话获取全文。EasyScholar 不授予收费数据库权限。
学校访问需要真实入口、宿主浏览器/secret 能力、用户完成 MFA，以及学校实际订阅；
没有通用学校登录器，不自动购买。

无全文/图片工具时可以搜集候选，但相应内容维度保持待评；无下载/文件工具时不能
声称已保存和核验。尚未完成所有 harness、真实学校登录与订阅访问的端到端测试。
详见 [全文访问](research-radar/references/fulltext-access.md)。

## 项目维护

安装包仅含 Markdown 指令、模板、可选 UI 元数据与 MIT 许可，不含可执行研究流水线。
仓库维护者可用 Node.js 20+ 标准库检查结构、保护公开配置示例和构建可复现归档；
以下工具不随 skill 分发，也不是使用 skill 的要求：

```bash
node --test tests/package.test.mjs
node scripts/check-skill.mjs
node scripts/package-skill.mjs
```

归档生成到被忽略的 dist/。
[验收场景](tests/acceptance.md) 用于在真实宿主里复核行为；
结构/打包检查不代表学术准确性或端到端兼容已经验证。
旧程序入口及配套测试已移除，旧测试数量不适用于当前架构。

采用 [MIT 许可](LICENSE)。
