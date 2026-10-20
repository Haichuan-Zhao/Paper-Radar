# Paper-Radar

这是一份可直接打开的本地工作区。保留隐藏目录，先编辑 USER_CONFIG.md，
再向当前宿主发送真实研究问题。配置可使用中文或英文，不需要运行项目程序。

This is a local workspace. Keep hidden folders, edit USER_CONFIG.md, then give
your real research question to the host agent. No project runtime is required.

## 启动 / Start

Codex 用 $paper-radar；Claude Code 用 /paper-radar，也可要求读取完整 SKILL.md。
Use $paper-radar in Codex or /paper-radar in Claude Code.

> 使用 paper-radar，读取 USER_CONFIG.md，围绕我的真实问题深入检索、核验与评审。
> 若宿主支持，我授权在本任务范围与预算内使用原生子 agent 分工。
> 保存 RADAR.md，先给固定编号清单，等我选择后下载。

> Use paper-radar with USER_CONFIG.md. Search deeply, verify sources and assess
> actual evidence for my real research question. If supported, I authorize native
> subagents within this task and budget. Save progress in RADAR.md and deliver a
> fixed numbered list before waiting for my download selection.

首次缺项会先说明影响并让你选择补全或本次接受限制。只配置不启动研究。
The agent checks missing settings before searching. Configuration alone does not start research.

## 查看、暂停与恢复 / Inspect, pause, resume

结果在配置目录的每个 run 中；agent 会给出 RADAR.md 的实际位置。
顶部保存已知、未知、预算与下一步，下方保留实际轮次和证据位置。
暂停时要求保存进展；恢复时给出该路径，先核对产物与剩余预算。
下载明确指定该清单编号，例如“下载第 1、3 篇”。

The agent shows the actual run/RADAR.md path. Inspect its current state, ask to
save progress before pausing, and specify it when resuming. Downloads require
your selection from a particular numbered list.

密钥直接填文档属于明文，可能被宿主/模型读取；优先 secret 引用或真实网页登录。
学校账号不证明单篇订阅。无真实子 agent 时只能标为 self_check。
Inline secrets are plaintext. Prefer secret references or human browser login.
A school account is not proof of article access. Sequential checks are self_check.

项目与完整说明 / Project:
https://github.com/Haichuan-Zhao/Paper-Radar
