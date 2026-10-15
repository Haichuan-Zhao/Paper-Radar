# Research Radar

[English](README.md) | 简体中文

**围绕研究问题找论文，依据证据评估，再下载你选择的文献。**

面向研究者的可移植文献筛选 skill：从用户原始需求检索期刊论文和预印本，
核验论文/期刊身份与版本，再依据全文、方法和图表证据评价内容质量 Q 与需求
匹配度 M，形成有理由、有局限说明的阅读清单。使用宿主自身的 LLM。
采用两步流程：**先检索并评估，展示带编号的结果；用户选择后再下载指定论文。**

采用 [MIT 许可证](LICENSE)。运行要求 Python 3.9+ 标准库与 HTTPS；全文阅读、
图片查看和机构登录由宿主提供相应能力。

## 从一份配置文档开始

安装完整 [research-radar/](research-radar/) 目录到支持 Agent Skills 的宿主，
或让 agent 读取 [SKILL.md](research-radar/SKILL.md) 并执行其中的 CLI。
不同宿主的发现/执行方式见 [部署说明](research-radar/references/deployment.md)。

1. 复制 [用户配置文档](research-radar/USER_CONFIG.template.md) 到自己的
   user-data/config.md，填写主题、原始需求、阅读目的和必要限制。
2. 让 agent 根据原话补全英文检索式、概念组与明确日期；在同一份文档填写
   自己的 key 的读取位置、评级偏好，以及可选的学校访问入口。
3. 从 skill 目录执行以下命令，或让宿主按 skill 的绝对路径执行。

```bash
python3 radar.py validate --profile /path/to/user-data/config.md
python3 radar.py preflight --profile /path/to/user-data/config.md
python3 radar.py run --profile /path/to/user-data/config.md --out /path/to/user-data/new-run
```

JSON profile 同样支持。配置文档相对路径基于文档所在目录，运行结果使用新目录。
普通检索产生候选和评审模板；agent 阅读实际全文及图表、填写 reviews 后执行：

```bash
python3 radar.py assess --run /path/to/user-data/new-run --reviews /path/to/reviews.completed.jsonl
```

EasyScholar key 和学校邮箱都从这份配置文档开始设置，无需项目服务器或网页上传。
从 skill 目录在自己的交互终端执行：

```bash
python3 scripts/credentials.py configure --service easyscholar --out /path/to/user-data/private/api-keys.json
python3 scripts/institution_credentials.py configure --profile my-school --out /path/to/user-data/private/institution-accounts.json
```

第一条隐藏输入 key；将文档中的 easyscholar.credentials_file 改为
"private/api-keys.json"。第二条先输入学校邮箱/图书馆登录账号，再输入密码；学校
用学号登录就填学号。文档内 routing 填学校、图书馆与 SSO 网址，填好后启用机构访问。
邮箱本身不能确定登录入口或订阅权限。私有文件为本地明文、POSIX 权限 600；
也可使用宿主私密环境变量。用户数据放在项目外，或已忽略的 user-data/ 下。
详见 [凭据说明](research-radar/references/credentials.md) 与
[机构适配说明](research-radar/references/institution-login.md)。

模板、配置脚本和 [运行前检查说明](research-radar/references/preflight.md) 均包含在
skill 分发包内。每次 run 都先检查：配置缺项返回退出码 3，在任何检索之前让用户
选择先补全还是接受列明的限制继续。只有用户已选择继续，宿主才加
--continue-with-gaps；决定和临时降级写入本次 preflight.json，不改用户原文件。
本地凭据存在与远端有效、真实登录、论文订阅权限分别记录。

## 两步使用

1. **搜集并打分**：默认 deep，多组互补检索式、多来源及完整分页，继续扩词、
   前后向引用追踪与漏检补查，记录轮次、覆盖及停止原因；count 只限制阅读目标，
   不限制候选搜集。按原始提示核验、阅读和评分，展示固定编号、Q/M/S、
   评级来源、匹配理由、局限及获取状态。第一步允许打开合法全文和临时阅读缓存；
   无法读到完整证据时保留 Q/S 待评，不自动归档整批 PDF。assess 输出
   reading-list.md 和 selection-catalog.json。
2. **选择后下载**：用户回复“下载第 1、3、5 篇”，agent 核对这份结果的编号与版本，
   仅下载所选正文，验证文件并逐篇报告结果；SI 和 Zotero 导入按另行明确的需求执行。

宿主用下面的命令生成第二步计划，然后通过自己的合法获取工具执行：

```bash
python3 radar.py select --assessment /path/to/user-data/new-run/assessment --numbers 1,3,5 --out /path/to/user-data/chosen-downloads
```

select 生成 download-plan.json 和 selected-papers.jsonl，核验编号对应的论文与版本，
不发起网络请求。实际下载依赖宿主文件/浏览器工具，获取方式与校验要求见
[下载说明](research-radar/references/download-and-zotero.md)。

深度检索由宿主按 search-plan.json 执行并填写 search-ledger.completed.json，
可用 radar.py audit-search 核验步骤、引用来源及连续零新增轮次；内置关键词
查询本身不会自动遍历引用。预算/授权/分页受限时标记部分检索。详见
[深度检索与日志协议](research-radar/references/discovery-and-evidence.md)。

## 筛选依据

| 能力 | 实现与边界 |
|---|---|
| 文献检索 | Crossref、OpenAlex、arXiv、bioRxiv、medRxiv；保留分页、失败和截断的覆盖记录 |
| 精确匹配 | DOI/原生 ID 与版本、有效 ISSN/ISSN-L、同名刊冲突；不自动合并模糊刊名 |
| 期刊评级 | 用户自己的 EasyScholar key、机构 CSV/JSON；IF、JCR、WoS、CAS、CCF 和自定义评级保留来源及年份 |
| 内容与匹配 | Q/M 分开，默认 S=Q^0.6×M^0.4；Q/M 均≥70，rigor/evidence 均≥3/5 |
| 全文获取 | 已有 OA 链接、可选 Unpaywall/Europe PMC、用户文件、机构会话；不自动购买订阅 |
| 评审与交付 | 证据锚点、真实阅读版本、分项得分、阅读理由、局限和待获取清单 |

作者声望、高 IF 和精美图片不直接加内容分；预印本缺 IF 不扣分。最终质量需要
阅读全文并真正看图，摘要只作初筛。缺证据保持待评，不填 0 或平均分凑数。
评分权重是初始设计，可用人工标签校准，尚未完成领域准确率或召回率基准验证。

评审使用 schema v5 / content-v4：逐条记录核心主张、支持与限制证据、实际适用
范围及保守结论。优势、局限和阅读理由区分作者报告与评审判断并绑定原文锚点；
重大疑点需针对性复核。核心主张未决时不生成最终 Q/S；主张需收窄时限制评分与
推荐等级，不能用高综合分掩盖。旧评审需重新生成模板并补做审查。
这些检查核验结构和证据声明，不能自动证明论文正确或保证消除 overclaim。

匹配、评分、获取分别见 [matching.md](research-radar/references/matching.md)、
[scoring.md](research-radar/references/scoring.md)、
[fulltext-access.md](research-radar/references/fulltext-access.md)。

机构凭据层与适配协议已经提供；具体网页的填写和会话校验需要宿主浏览器适配器，
尚未验证真实学校登录。EasyScholar 不授予付费数据库全文权限。仅有脚本执行能力的
宿主可完成元数据检索；阅读全文和图片评估仍取决于宿主实际具备的工具。

## 开发与分发

```text
research-radar/       唯一的 skill 源码、用户配置模板、参考协议和测试
scripts/             发布打包和独立验证
.github/workflows/   离线测试与分发包检查
README.md            英文介绍
README.zh-CN.md       中文介绍
LICENSE              MIT
```

在项目根目录执行：

```bash
python3 -m unittest discover -s research-radar/tests
python3 scripts/check_release.py
```

第二条命令构建并独立解压验证 dist/research-radar.zip 和 dist/research-radar.skill，
检查文件白名单、哈希、文档链接及 CLI。dist/ 是可重建的发布产物，不进入源码提交；
GitHub Release 可附带这两个归档。测试使用模拟数据，不需要真实 key 或学校账号。
自动化通知和 Zotero 导入为可选功能，只有用户明确请求相关操作时执行。
