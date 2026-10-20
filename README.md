# Paper-Radar

**围绕研究问题，深入发现、核验和评价值得读的论文。**

**简体中文** · [English](README.en.md) · [MIT](LICENSE)

由 Codex、Claude Code 等 harness 直接执行的一份通用 skill：
**检索 → 核验 → 全文评审 → 针对缺口补查 → 编号结果 → 用户选择后下载**。
用 RADAR.md 保存进展，支持暂停和恢复；研究使用无需 Python、Node 或额外模型 API。

## 安装与配置

下载 [最新正式安装包](https://github.com/Haichuan-Zhao/Paper-Radar/releases/latest/download/paper-radar.zip)
或查看 [所有版本与更新说明](https://github.com/Haichuan-Zhao/Paper-Radar/releases)。
解压后，将完整 paper-radar/ 放到宿主的一个 skill 目录：

| 宿主 | 个人使用 | 项目使用 |
|---|---|---|
| Codex | ~/.agents/skills/paper-radar/ | .agents/skills/paper-radar/ |
| Claude Code | ~/.claude/skills/paper-radar/ | .claude/skills/paper-radar/ |

也可让 agent 按 [安装与更新指南](paper-radar/references/install-update.md) 操作。
其他 Agent Skills 宿主使用同一份目录；本地/云端发现方式见
[Codex](https://learn.chatgpt.com/docs/build-skills)、[Claude Code](https://code.claude.com/docs/en/skills)。

在自己的研究工作区编辑一份 USER_CONFIG.md，由 agent 从
[配置示例](paper-radar/USER_CONFIG.example.md) 创建。主要填写：

- 研究问题、日期、必须条件、阅读目的与预算，也可在聊天中给本次需求。
- 自己的 EasyScholar key/secret 引用，或合法本地评级表。
- 需要机构访问时填写学校、真实图书馆/SSO 入口、邮箱/账号与会话说明。

配置、论文和研究结果放在 **skill 目录之外**；升级仅替换 skill。
直接填写的 key/密码是明文，可能被宿主/模型看到；优先 secret 引用或真实网页登录。
每次检索前检查相关配置，缺项先由用户选择补全或本次接受限制。

## 使用

Codex 用 $paper-radar，Claude Code 用 /paper-radar，例如：

> 使用 paper-radar 和我的 USER_CONFIG.md，深入搜集与本次问题匹配的论文。
> 核对身份与期刊评级，基于真实全文证据评价质量和匹配度，针对缺口补查。
> 保存 RADAR.md，先给固定编号结果，等我选择后再下载。

有实际子 agent 且获授权时分工，无此能力时标单 agent 自查；无需另配宿主角色文件。
默认最多六轮实质性工作、精读目标十篇，篇数不限制候选池；预算不足交付部分结果。
之后可回复“下载目录修订 1 的第 1、3 篇”，或指定 RADAR.md 暂停/恢复。

Q 评价内容质量，M 评价原始需求匹配，默认 S=Q^0.6×M^0.4。
核心主张、证据、严谨性与硬约束先过门槛，再综合排序；IF、作者名望和漂亮配色不加分。
缺全文/关键证据时最终 Q/S 待评，重大批评也须验证，避免作者和评审者双方 overclaim。
预印本单独标注状态；EasyScholar 不提供收费全文权限，学校登录不等于单篇有订阅。

## 已安装用户如何更新

对 agent 说：

> 更新 paper-radar 到最新正式版。先确认我正在用的安装路径和本地修改，
> 按更新指南核对发布包，保留 USER_CONFIG.md、密钥、论文和研究记录，更新后报告版本。

版本在 skill 的 [VERSION](paper-radar/VERSION)。每次 release 都提供安装包与逐文件哈希清单。
更新先检查本地改动、备份，再完整替换已确认的 skill；新增配置只补缺项，失败可回退。
**git pull 只更新源码克隆，不会自动同步已经复制到宿主的 skill。**
Source code ZIP 没有 Git 历史，不能直接 pull；重新下载正式包即可。
旧版无 VERSION、曾用双宿主完整包或有本地定制，按 [迁移规则](paper-radar/references/install-update.md) 处理。

## 维护与验证

仓库只维护一份 [skill](paper-radar/)，不再提交重复 ZIP、宿主适配包或角色副本。
维护者修改 VERSION、推送 main，通过 Actions 的 Run workflow 发布。
CI 校验后以 v<版本> 建立正式发布，附唯一通用包与 manifest；已发布版本不重复覆盖。
操作依据 [GitHub 手动运行工作流](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)。
维护检查使用 Node.js 20+ 标准库，不随 skill 分发：

```sh
node --test tests/package.test.mjs
node scripts/package-skill.mjs
```

[行为验收](tests/acceptance.md) 与 [合成材料](tests/fixtures/casepack.md) 记录验证范围。
分发测试不证明科学准确率；真实学校访问、key 和各宿主仍需按实际环境验证。
运行思路借鉴 [Auto-Loop](https://github.com/Haichuan-Zhao/Auto-Loop) 的任务循环、职责交接与恢复记录。
