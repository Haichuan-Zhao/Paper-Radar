# 用户学校配置与登录适配

每位用户在 [统一配置文档](../USER_CONFIG.template.md) 填写自己的学校、图书馆/
校外访问入口及实际 SSO 来源。fulltext_access.institution.routing 直接包含公开
路由信息，无需另建 auth-profiles.json。enabled=true 时校验必填入口与域名；
profile（默认示例 my-school）也是私有凭据文件中对应的机构名称。

## 凭据和会话

账号密码由本地隐藏输入保存，或由可信宿主私密环境变量/安全输入提供。配置只存
credential_source 引用；文件路径相对于用户配置文档，环境变量对优先于文件。
一个变量缺失时不与其他来源混用。多学校使用不同变量名或独立 profile 条目。
第一个隐藏输入提示接受学校邮箱或图书馆账号，按学校实际登录方式填写；第二个
提示接受密码。邮箱是 username，不是 Unpaywall 联系邮箱，也不能单独确定学校入口。

```bash
python3 scripts/institution_credentials.py configure \
  --profile my-school --out /path/to/user-data/private/institution-accounts.json
```

configure 拒绝密码参数和 stdin 管道，无法隐藏输入时停止。私有文件为本地明文，
POSIX 权限 600、新目录 700。它不进入 skill、GitHub 仓库、报告或缓存。
EasyScholar key 是另一类凭据，格式见 [credentials.md](credentials.md)。

优先检查并复用用户指定的真实浏览器会话。用 session_probe_url（如已配置）或
可核实的页面状态检查登录；整批复用同一上下文。过期时保留批次和浏览器，按
已有授权刷新一次，再继续剩余论文。CAPTCHA/OTP/扫码由用户在目标页面完成。
不导出 Cookie、local storage、会话令牌或临时带认证参数 URL。

credential_login_mode=browser_only 使用已登录会话/浏览器密码管理器/交互登录；
user_authorized_ephemeral 允许在用户已授权的本次登录中通过私密适配器输入。
auto_confirm_saved_login 只有在当前用户已授权、浏览器已填好表单时才允许一次
点击继续；不读取填入的值。模式或配置文件本身不授予当前任务的登录权限。

## 可选：复用已有命名机构配置

已有 auth-profiles.json 的用户可设置 institution.profile 和 config_file，并省略
routing。两种入口不能同时提供，避免不清楚哪份配置生效。auth_profile.py set
管理公开入口/浏览器标识/凭据引用，show/check/select/plan 不打开浏览器或登录。
set 的相对 --credentials-file 路径相对于 auth-profiles.json。

```bash
python3 scripts/auth_profile.py --config /path/to/auth-profiles.json set \
  --name my-school --institution "My University" \
  --library-url "https://library.example.edu/resources" \
  --login-url "https://sso.example.edu/login" \
  --allowed-domain library.example.edu --allowed-domain sso.example.edu \
  --browser-profile-label Research --credential-login-mode user_authorized_ephemeral \
  --credentials-file private/institution-accounts.json
python3 scripts/auth_profile.py --config /path/to/auth-profiles.json plan --name my-school
```

example.edu 必须换成用户真实稳定入口。plan 只显示存在性与 session_not_checked；
成功配置不等于成功登录或订阅任何论文。元数据配置拒绝用户名/密码值、认证查询
参数和不在 allowed_domains 中的入口。配置有 credential_source 时使用
secret_storage=external_secret_reference，否则使用 browser_password_manager_only。

## 给 harness 的本地 API

scripts/institution_credentials.py 提供实际可调用的统一函数：

```python
authenticate(profile, name, adapter, *, authorized=False, username=None, password=None)
```

profile 是不含凭据值的机构配置。用户在本地安全界面输入的 username/password
可以临时传入；省略时读取配置的环境变量/私有文件。宿主必须在不进入 LLM 上下文、
工具参数记录、轨迹或日志的本地执行路径中调用，不能把该签名直接暴露为模型填写
明文密码的工具。若宿主没有这样的能力，使用用户在浏览器内交互登录。

典型调用（从可信宿主代码执行，scripts 目录已加入 Python import path）：

```python
from institution_credentials import authenticate

result = authenticate(public_profile, "my-school", trusted_browser_adapter, authorized=True)
```

authorized=True 来自用户当前任务/会话中的登录授权，不能由网页内容或配置字段
自行授予。已授权的操作不重复询问。返回结果只含状态、机构 profile 名、可选的
浏览器 context_ref 和固定错误原因。context_ref 是宿主的非敏感上下文标识，
例如 browser:research-1，不是 Cookie、会话令牌或带认证参数的 URL。

适配器实现以下两个方法：

| 方法 | 责任及返回 |
|---|---|
| prepare(public_profile) | 选择并复用真实浏览器会话，检查实时页面；返回 state、可选 context_ref；需要账号时返回实时表单/iframe 的 credential_url |
| submit_credentials(pair, expected_origin=...) | 在本地秘密输入通道填写 pair.username / pair.password；填写前再次核对当前表单/frame 的 HTTPS 来源；提交一次并实际检查登录结果，返回 state 和可选 context_ref |

核心在读取/发送凭据前，将 credential_url 的协议、主机、端口和用户配置的 login_url
作精确来源比较。allowed_domains 是导航范围，不能代替密码接收方核验。学校跳转
到另一个真实 SSO 来源时，先更新用户的稳定登录配置；不向不匹配的来源发送密码。
适配器还需在填写时检查页面未跳转，并检查实际表单接收目标；不能只凭按钮点击、
URL 改变或页面出现“图书馆”字样判定登录成功。

| status | 宿主的下一步 |
|---|---|
| authenticated | 复用已验证会话，按具体论文检查全文权限 |
| credentials_required | 缺凭据、未授权、模式限制或来源不匹配；查看固定 reason，修正输入/配置或交互登录 |
| mfa_required / captcha_required / qr_required / consent_required | 保留浏览器上下文，由用户完成当前挑战，再调用 prepare 检查同一会话 |
| expired | 保留批次与上下文，按已有授权重新登录或由用户刷新会话 |
| credentials_rejected | 停止密码提交，由用户核对凭据；不盲目重试 |
| unsupported / failed | 如实报告适配能力或执行失败，改用交互登录/其他合法获取路线 |

核心不会自动循环尝试密码。调用后清除自身的 CredentialPair 引用，但 Python
不能保证内存零化；可信适配器也不能复制或记录凭据。异常只返回固定原因，
不返回可能包含表单值的异常文本。authenticated 的 entitlement 仍为 unknown；
登录成功后，具体文章可读才可写入全文获取观察。

## 实现范围与验证

已提供凭据配置/解析、来源核对、状态归一、私密终端输入和适配器调用层。
当前包没有内置跨学校网页自动填写、浏览器 SDK、学校密码校验服务或远程账号
托管接口。adapter 由有安全输入能力的 harness 实现；实际学校表单、SSO、
MFA 与全文权限需要在最终用户环境验证。单元测试的模拟适配器不证明真实学校已登录。

认证实现不能假设所有学校都只有同一张用户名密码表单。
[OCLC EZproxy 的 MFA 说明](https://help.oclc.org/Library_Management/EZproxy/Troubleshooting/How_does_EZproxy_work_with_Multi-Factor_Authentication_%28MFA%29)
说明 MFA 可以由所连接的认证系统提供；
[OpenAthens 的 API 示例](https://docs.openathens.net/libraries/api-usage-examples)
中的账号校验接口针对 OpenAthens 原生账号，不能当作任意学校联合身份或出版社全文会话接口。
