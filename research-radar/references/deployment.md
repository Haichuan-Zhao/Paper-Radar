# Harness 安装与可移植性

机构账号接口见 [institution-login.md](institution-login.md)：每位用户配置自己的学校、
入口和凭据来源。核心提供本地凭据读取与登录适配协议；宿主需要实现具备私密输入
和实时页面核验的浏览器适配器。没有该能力时，使用用户交互登录及会话复用。
用户名密码不进入 LLM 工具参数，也不随 skill 一起分发。尚未验证各学校的真实登录。

分发单元是完整 research-radar/：SKILL.md、radar.py、scripts、references、示例以及可选 agents/openai.yaml。Python 3.9+ 标准库和 HTTPS 即可，无其他 skill、第三方包或固定 MCP 依赖。

支持 Agent Skills 的宿主按自身安装/发现机制加载整个目录；没有自动发现的宿主可读取 SKILL.md 并按绝对路径执行 CLI。只能聊天、不能执行脚本的环境由用户本地执行后提供产物，不可声称自动运行成功。具体发现路径与权限随 harness 版本变化，以该产品文档为准；通用 skill 不硬编码私有工具名/用户主目录。agents/openai.yaml 仅是支持它的宿主的 UI 元数据。

1. 将整个目录安装到用户选择的 harness。
2. 复制 [用户配置文档](../USER_CONFIG.template.md) 到用户数据目录，填写问题、queries、概念组和需要的评级开关。该 Markdown 可直接作为 --profile 输入，JSON 同样支持。
3. 配置 secret 环境变量、引用本地私人 credentials JSON，或用 credentials.py configure 隐藏输入 key。学校邮箱/账号用 institution_credentials.py configure 的第一个提示输入，第二个输入密码；公开入口仍填在同一配置文档。
4. 执行 validate、preflight；缺项由用户选择补全或接受限制继续，未选择前不开始检索。run 再次检查，只有已接受缺口才加 --continue-with-gaps。协议随包提供，见 [preflight.md](preflight.md)。
5. 默认执行深度计划：多来源/查询分页，再由宿主扩词、引用追踪和缺口补查，填写检索日志并 audit-search；count 不限召回。agent 读取 matching-audit、coverage、review packet，实际阅读全文/图表/已有工作并填写 reviews，运行 assess 得 Q/M/S、带固定编号的阅读清单与 selection-catalog.json，报告实际覆盖，交付第一步结果并等待用户选择；可用人工标签 calibrate。
6. 用户选择后，用 radar.py select --assessment RESULT_DIR --numbers 1,3 --out NEW_DIR 生成精确计划；宿主按计划获取并校验文件，交付第二步下载结果。select 本身只生成计划，无网络操作。

数据文件相对 profile；脚本/参考相对 skill。JSON/JSONL/CSV/Markdown 协议便于在不同宿主复用。网络/授权缺失如实报告覆盖范围。

全文路由见 [fulltext-access.md](fulltext-access.md)。脚本无密钥即可复用来源的 OA 元数据；Unpaywall 补查需每位用户自己的联系邮箱。机构配置绑定真实稳定入口及原有浏览器，会话和付费权限由宿主实际确认。不能操作浏览器的 harness 仍可使用 OA/已有用户文件并输出机构 handoff；它不能凭 profile 声称完成了订阅访问。review schema v5 绑定实际阅读材料与版本，另需核心主张审查及有锚点的交付判断，缺全文保持待评和待获取。

科学判断使用宿主自身 LLM，不依赖固定厂商、MCP 或另一套模型 API key。全文/PDF/图片能力因宿主而异：真正看图才填写 figures_inspected；纯文本或无全文环境保持相关维度 null 和待评。作者/期刊 context 与内容 packet 分开，减少声望对判断的影响。

从开发项目根执行 `python3 scripts/package_skill.py`。固定白名单仅纳入入口、示例、Python helper、references 和 UI 元数据，排除测试、真实配置、credentials、cache、runs、bytecode。产出 ZIP、.skill 归档及 SHA-256 manifest。解压到独立目录运行 --help/validate/doctor 验证开发目录独立性。打包通过不代表已在所有 harness 实际安装测试。
