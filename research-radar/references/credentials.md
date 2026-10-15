# 用户凭据

每位研究者提供自己的 key。EasyScholar 读期刊评级及账号自定义数据；OpenAlex key 用于较多检索和多页 cursor；Crossref 公共查询不需要 key。

统一入口是用户自己的 [配置文档](../USER_CONFIG.template.md) 副本。没有网页上传服务；
用户可把已有 JSON 放在本地私有目录，或在交互终端从 skill 目录执行隐藏输入：

```bash
python3 scripts/credentials.py configure --service easyscholar --out /path/to/user-data/private/api-keys.json
```

将文档里的 easyscholar.credentials_file 改为 "private/api-keys.json"。
可选 OpenAlex 使用同一命令，将 --service 改为 openalex，并填写 openalex.credentials_file。
命令只返回已保存状态，拒绝 key 参数和 stdin 管道；更新某个服务时保留另一服务。
文件是本地明文，POSIX 权限 600、新建私有目录 700。不要让 agent 读取/回显文件正文，
用 doctor 检查是否配置。学校邮箱/账号通过 institution_credentials.py 的第一个
隐藏提示填写，不写在 API key JSON；格式和实际登录能力见 [institution-login.md](institution-login.md)。

优先用 harness secret 环境变量 EASYSCHOLAR_SECRET_KEY/OPENALEX_API_KEY。上传 JSON 时引用本地路径，不要转录内容进命令/回复。文件支持：

```json
{
  "easyscholar": {"secret_key": "YOUR_OWN_KEY"},
  "openalex": {"api_key": "YOUR_OWN_OPTIONAL_KEY"}
}
```

也支持单服务对象。profile.easyscholar.credentials_file 和 openalex.credentials_file 相对于 profile；环境变量 > 凭据文件 > 明确的内嵌值。内嵌 key 在校验/保存时仅显示 [REDACTED]。私人文件放在 installed skill/版本库之外，Unix 可设 600 权限；示例只含占位符，打包使用固定白名单。

validate 不联网；doctor 检查存在性，不打印 key、不验证额度/有效性。缺 EasyScholar key 时仍检索文献；HTTP/业务错误记录为失败，不当“期刊不收录”，不写成功缓存。缓存按 key 不可逆指纹隔离，避免不同账号 customRank 串用；TTL 默认 168 小时，原 retrieved_at 不改写，未来/损坏/超期时间戳不当新鲜缓存。

OpenAlex key 在 Authorization header 发送，driver 用子进程环境传递，不入日志。[官方 authentication](https://help.openalex.org/api/authentication/) 说明基础查询可不带 key，第二页 cursor 需要 key；缺失保留第一页面及 partial coverage。

[EasyScholar 开放接口](https://www.easyscholar.cc/console/user/open) 要求 GET 的 secretKey/publicationName；脚本编码刊名并拒绝重定向，错误仅含状态类型，响应中的凭据或 key 回显在缓存前脱敏。保留 officialRank.all/select 和 customRank 原始观测；未适配的评级字段不猜语义。文档未承诺 ISSN/年份，值不自动成为已核验指标。
