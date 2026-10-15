# 指标版次与时效

每项期刊/会议评级保存实际来源、edition（发布版次）、year（数据年）、检索时间、
类别和核验状态。API 读取成功、缓存新鲜、网站版权年份均不能证明某版指标最新。
未知版次不妨碍发现论文，但不能通过需要核验该指标的严格过滤。

- JCR/JIF 使用 [Journal Citation Reports](https://clarivate.com/academia-government/scientific-and-academic-research/research-funding-analytics/journal-citation-reports/)
  或 [授权期刊 API](https://developer.clarivate.com/apis/wos-journal)。保留版次和数据年，
  以及全部 JCR 学科。SCIE/SSCI/ESCI/AHCI 单独依据
  [Master Journal List](https://mjl.clarivate.com/home) 或授权 WoS 记录核验。
- CAS 使用 [官方分区平台](https://www.fenqubiao.com/) 公告/版次选择器或授权导出，
  分别记录大类与小类。不将替代平台评级改称 CAS，也不将示例年份写为永久最新。
- CCF 使用 [官方目录与通知](https://www.ccf.org.cn/Academic_Evaluation/By_category/)，
  记录目录版次、修订及论文 track；不能把主会议评级授予未核实的 workshop/短文。

## 可选的版本登记工具

已有官方依据时，用独立 helper 登记；文件位于用户目录：

```bash
python3 scripts/metric_registry.py --registry /path/to/metric-registry.json init
python3 scripts/metric_registry.py --registry /path/to/metric-registry.json update \
  --source jcr --latest-official-edition '<verified-release>' \
  --local-data-edition '<loaded-release>' \
  --source-url 'https://clarivate.com/<observed-official-release-page>'
python3 scripts/metric_registry.py --registry /path/to/metric-registry.json status --sources jcr,cas,ccf
```

update 保存宿主核验的声明，不会查询或登录评级服务。只有 status=verified、
官方/本地版次一致、来源与时间有效且检查未过期时，status 才显示 current。
默认检查有效期为 24 小时，可配置；这是本地缓存规则，不代表评级每天更新。

当前 driver 不自动强制使用该独立登记表。用户要求“最新已核验评级”时，宿主
先查官方发布依据，再检查候选所用指标版次；将这一要求记录为带 id/description
的 hard_constraint，并在评审中用证据判定。无法核实则保持 unknown/待核验，
不能自动改用历史版通过。历史对比可使用明确标注的历史版次。

使用的登记快照与候选指标一并保存在运行证据中。不要把授权评级数据库、用户
学校导出表或真实 key 放进开源分发包；样例均不能当作生产评级数据。
