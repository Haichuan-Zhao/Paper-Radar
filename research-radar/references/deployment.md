# 在 harness 中安装与使用

分发单元是完整的 research-radar 文件夹。宿主读取 SKILL.md，再按需读取 references
与 assets，并用自己现有工具操作。没有研究运行时、依赖安装或固定模型/MCP 要求。
agents/openai.yaml 仅供支持它的宿主显示 UI；其他宿主可忽略。

## 安装位置

| 宿主 | 个人使用 | 项目使用 | 显式调用 |
|---|---|---|---|
| Claude Code | ~/.claude/skills/research-radar/ | .claude/skills/research-radar/ | /research-radar |
| Codex | ~/.agents/skills/research-radar/ | .agents/skills/research-radar/ | $research-radar |
| 其他 Agent Skills 宿主 | 按该宿主安装完整目录 | 按其发现机制 | 指明使用 research-radar 或读取 SKILL.md |

这些路径核对于 2026-10-15 的
[Claude Code 官方说明](https://code.claude.com/docs/en/skills) 和
[Codex 官方说明](https://learn.chatgpt.com/docs/build-skills)；
旧版本、托管云或受管环境按实际产品要求操作。不要承诺所有版本已经实测。

下载仓库后，可以直接让 agent：
“把这里的 research-radar 文件夹安装到我指定的 skill 目录，不覆盖已有个人配置。”
安装和配置不自动触发文献检索。对安装的授权不包括开启新连接器或改宿主安全设置。

## 使用

首次调用说“使用 Research Radar 帮我配置”。agent 会将 USER_CONFIG.example.md
复制到当前研究目录的 USER_CONFIG.md，并给出可打开的路径；用户直接编辑表格。
个人 key、学校邮箱/账号、真实图书馆入口及偏好在同一文件里维护。
后续也可指定“读取另一目录中的 USER_CONFIG.md”。

然后用聊天提出问题：
“使用 Research Radar，读取我的 USER_CONFIG.md，深入查找与这个问题匹配的论文，
先给带编号、质量/匹配分、证据局限和获取状态的结果，等我选择后再下载。”

## 实际能力决定执行范围

| 宿主能力 | 能完成的工作 | 缺失时的边界 |
|---|---|---|
| 文件读取 | 读取 skill、配置和证据 | 由用户提供内容，不假称已安装/读取 |
| 搜索、网页或文献连接器 | 真实检索、核验来源和引用追踪 | 无网络就不能声称完成在线搜集 |
| PDF/全文 | 阅读实际版本的方法、结果和局限 | 摘要初筛，Q/S 待评 |
| 图片/页面渲染 | 实际检查图表 | 未看图保持对应维度待评 |
| 私密 HTTP/secret 能力 | 调用用户的 key | 不把 key 暴露给公共搜索工具 |
| 浏览器会话 | 机构网页与人工登录交接 | OA/用户文件与机构待获取队列 |
| 文件写入/下载/检查 | 保存结果、下载并验证所选论文 | 交付聊天结果或链接，下载状态待完成 |

不要为适配不同工具名重写 skill 的科学规则。选用本次确实可用的工具，
缺少能力按 [运行前协议](preflight.md) 征求取舍。skill 不能给宿主新增工具或权限。

## 从旧版迁移

当前版本移除了原来的程序入口和 JSON profile 工作流。旧文献和个人凭据无需删除；
用户可以在新配置文档中引用既有私密存储，由宿主按自身能力读取。
旧评审是历史材料，不能直接冒充本次 agent 的实际阅读、证据审查或下载记录。
旧测试数量不能作为当前纯 skill 的行为验证结果；维护检查只覆盖结构和分发。
