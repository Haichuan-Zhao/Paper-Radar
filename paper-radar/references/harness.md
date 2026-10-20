# 宿主安装与实际角色绑定

标准分发单元是 paper-radar/，正文、角色与模板自包含。
无需其他 skill、固定 MCP、Python/Node 运行时或新模型 API；宿主工具决定可执行范围。
不改现有 AGENTS.md/CLAUDE.md、安全设置、模型或权限来适配本 skill。

## 安装入口

| 宿主 | 项目 skill | 个人 skill | 本仓库可选角色模板 |
|---|---|---|---|
| Codex | .agents/skills/paper-radar/ | ~/.agents/skills/paper-radar/ | adapters/codex/agents/ → 项目 .codex/agents/ |
| Claude Code | .claude/skills/paper-radar/ | ~/.claude/skills/paper-radar/ | adapters/claude-code/agents/ → 项目 .claude/agents/ |
| 其他支持 Agent Skills 的宿主 | 按实际发现机制复制完整目录 | 按该宿主文档 | 使用原生通用子 agent 绑定角色文件 |

调用：Codex 用 $paper-radar，Claude Code 用 /paper-radar；也可直接要求读取完整 SKILL.md。
只有用户请求安装时才写入其指定目录，不覆盖既有个性配置。
完整宿主工作区包由维护工具生成，包含对应隐藏目录与空白 USER_CONFIG.md；
保留隐藏目录、在解压后的 Paper-Radar 根目录打开。不要合并到陌生项目后覆盖同名文件。

安装与角色字段依据 2026-10-20 的
[Codex skills](https://learn.chatgpt.com/docs/build-skills)、
[Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)、
[Claude Code skills](https://code.claude.com/docs/en/skills)、
[Claude Code subagents](https://code.claude.com/docs/en/sub-agents)。
这些是本地安装路线；云、受管环境和旧版本按真实产品能力处理，不能外推已实测。

## 原生委派

仅在实际工具可用、任务授权允许且预算足够时分派：
Codex 模板名 paper_scout / paper_verifier / paper_reviewer；
Claude Code 模板名 paper-scout / paper-verifier / paper-reviewer。
模板只绑定职责，不指定模型、不扩大权限，科学规则只在 skill 的 references 中维护。

每次分派传入已定位 skill 根目录/角色文件的实际绝对路径、用户原话与脱敏需求、
本轮范围、固定材料修订、剩余预算、允许工具和写入区。子 agent 不应假定
自动继承完整 skill 内容或读取私人配置，必须读取相应角色和引用协议。
角色未自动发现但有真实通用子 agent 时，采用文件绑定并记为 file_bound；
不要通过启动另一个外部模型进程伪造原生审查。

评审优先使用新上下文，先读原始问题与证据，后看发现方解释。
记录 context inherited/clean/unknown 与实际 agent ID；不同上下文仍可能共享文件、
进程和连接器。模板声明“只读”不是权限沙箱。

若没有子 agent 或当前政策/授权不允许，保留同一循环，顺序做发现、核验、评审，
标 self_check。若用户要求独立评审，则该要求仍待满足，不能冒充独立通过。
不为了凑三种角色启动无关工作，不让并发数超过宿主名额或导致同一路径竞争。

## 能力降级

无全文/图片时交付发现与待评队列；无网络时只处理给定材料并标范围。
无私密请求能力时采用用户选定的安全替代，不将 key 放公开工具参数。
无文件系统时用会话记录和固定清单，无真实下载能力不报保存成功。
由 intake 检查解释这些差异，不能把工具缺失写成论文缺陷。
