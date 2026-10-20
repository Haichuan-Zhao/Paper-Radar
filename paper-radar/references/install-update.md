# 安装、更新与回退

官方来源：https://github.com/Haichuan-Zhao/Paper-Radar。
当前版本读 skill 内 VERSION；研究记录沿用 paper-radar-v2，评分沿用 paper-content-v2。
这些操作只在用户明确请求时执行，不在检索前自动下载更新。

## 安装同一份 skill

从 [正式发布](https://github.com/Haichuan-Zhao/Paper-Radar/releases/latest) 获取
paper-radar.zip 与 manifest.json。先将 latest 解析为明确 tag，再从该 tag 下载两者，
不让跨版本请求混用；没有正式资产时说明发布未就绪，不静默改装 main。
核对 manifest 的仓库、版本/tag、ZIP 大小与 SHA-256，再核对解压后逐文件哈希和 VERSION。
只解压普通文件，拒绝绝对路径、路径穿越、重复条目、符号链接及清单之外的文件。
没有解压/校验能力时交接用户完成并如实标未核验；不执行包内代码。

| 宿主 | 个人安装 | 项目安装 |
|---|---|---|
| Codex | ~/.agents/skills/paper-radar/ | .agents/skills/paper-radar/ |
| Claude Code | ~/.claude/skills/paper-radar/ | .claude/skills/paper-radar/ |
| 其他 Agent Skills 宿主 | 按实际产品位置复制完整 paper-radar/ | 同左 |

路径依据 [Codex](https://learn.chatgpt.com/docs/build-skills) 与
[Claude Code](https://code.claude.com/docs/en/skills)，核对日期 2026-10-20；
这些是本地安装路线，受管/云端环境按实际产品能力处理。
尊重用户指定范围，不同时装个人和项目副本造成同名歧义，不改 AGENTS.md/CLAUDE.md。
若由现成技能管理器管理，沿用它的来源、更新和部署记录，避免旁路覆盖。
首次遇到已有安装目录时先当作更新检查；不把未知目录直接覆盖。

将配置示例复制到研究工作区 USER_CONFIG.md，已有文件不覆盖；结果/下载也放工作区。
安装路径、工作区配置路径、所装版本和来源向用户说明。配置不随 skill 移进共享目录。
Codex 用 $paper-radar，Claude Code 用 /paper-radar；未加载时按宿主规则刷新或重新开启会话。

## 更新：只更换已确认的安装副本

1. 找到用户当前调用的真实 SKILL.md 路径，确认宿主、范围和旧 VERSION；有多个副本时
   只处理本次明确对象，身份不清才澄清。用户下载的源码目录不等于实际安装目录。
2. 查看目标正式版本的发布说明和兼容性；pin tag 后取包与 manifest，按上面的检查暂存。
   版本相同且文件与正式版一致时无需替换；明确回退可使用旧 tag，不按字符串比较版本。
3. 对比旧目录与其 VERSION 对应的官方 tag，找出本地编辑、额外文件与符号链接。
   无法取得基线时标未知本地状态。完整备份到用户数据/缓存区，放在宿主扫描目录之外。
   发现用户修改先保留并给出差异；能无冲突保留则合并，冲突保留原安装并请用户选择，
   不让版本号覆盖本地修改的事实。正式版与合并后定制版须区分。
4. 用户配置、key、密码引用、PDF、RADAR.md、目录编号和下载记录保持原位。
   若旧版把个人文件放在 skill 内，先迁移到用户工作区并核对内容/路径；有冲突不覆盖。
   只向配置补充缺少的新字段和默认说明，不删除未知字段、不回显真实值、不重填凭据。
5. 暂存确认完整后替换整个已确认的 skill 目录，清掉旧版本独有文件；不要叠加复制留下
   失效 roles/assets。最后核对 VERSION、文件/链接和实际宿主加载路径。
   写入中断则从备份恢复；报告旧/新版本、差异、配置保持情况与备份位置。
   保留一份可回退备份，但不在工作区或 skill 扫描目录创建第二份活跃安装。

旧版没有 VERSION 时不猜版本或宣称未改动；按未知基线先备份、比较、保留个人文件。
旧完整工作区包中的 .codex/agents/paper-*.toml 或 .claude/agents/paper-*.md 已非必需；
仅在确认属于旧 Paper-Radar、与其官方旧版完全一致时清理，修改过/来源不明的文件保留报告。
升级不会自动重评历史论文、重置预算或修改已发布的清单；恢复任务先检查既有协议。

## Git 与手动下载

源码克隆更新可在检查本地修改后用 git pull --ff-only；分叉/冲突不 reset --hard 或强制覆盖。
这只更新克隆目录。已复制到宿主的 skill 仍须按上面流程同步；由管理器部署的走原管理器。
源码 main 是开发版，正式使用默认选 release；用户指定 main 时固定 commit 并说明来源。
下载 GitHub Source code ZIP 的用户没有可 pull 的 .git，更新应下载新正式包并替换安装目录，
不要把源码 ZIP、安装包和个人研究工作区当成同一个目录。

人工更新同样遵循：先保存配置/成果与本地编辑，核对新包，将整份 skill 更换后检查版本。
回退恢复旧 skill 备份，保留当前用户数据；协议不兼容时先报告差异，不反向改写数据。
