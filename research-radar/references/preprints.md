# 预印本检索与版本

sources 支持 arxiv/biorxiv/medrxiv；types 要包括 preprint。示例启用 arxiv，生物/医学方向可按需加 Rxiv。接口是 [arXiv API](https://info.arxiv.org/help/api/user-manual.html) 和 [bioRxiv/medRxiv API](https://api.biorxiv.org/)，不需要 EasyScholar key。未实现的平台可由宿主检索后按候选 schema 导入，不声称已有自动覆盖。

```json
{
  "sources": ["crossref", "openalex", "arxiv"],
  "preprints": {
    "arxiv_queries": ["(ti:battery OR abs:battery) AND (abs:\"state of health\" OR abs:SOH) AND (abs:generative OR abs:\"synthetic data\")"],
    "biorxiv_categories": [],
    "medrxiv_categories": []
  },
  "filters": {
    "preprint_venue_policy": "separate",
    "include_only": {"types": ["journal-article", "conference-paper", "preprint"]}
  }
}
```

arxiv_queries 接受官方 fielded Boolean 语法；为空时把画像 plain queries 转为 title/abstract 全词 AND，多条查询 OR 召回。规划替代术语，源端匹配后仍全文复核。Atom 按 start/max_results 翻页，请求间至少 3 秒。submittedDate 过滤首次提交（GMT），updated 与版本另存，不能用作正式发表日期。很早提交、最近修订的全部论文不在这一新提交窗口覆盖范围，需另做 update feed/已知 ID 跟踪。

Rxiv details 是 date/category feed，不支持任意全文 Boolean。每个 feed 抓一次，本地 title/abstract 每条 plain query 全词 AND、多条 OR，保留所有原始响应。不能套用 arXiv fielded 查询。词法可能漏掉同义表达，要规划替代词；feed 穷尽不证明语义召回完整。category 使用平台真实学科名；长窗口宜限制学科，空列表为全学科。

Rxiv date 是返回版本的 posting date，并非总是 v1。docs 写每页 30 条，脚本按实际批次和 total 翻页。重复分页、API 异常、无效记录、max-pages 截断均为 partial，保留证据。

arXiv ID+vN 独立评估；arxiv:doi 通常是发表版 DOI，仅记录 published_version 关系，不直接和期刊合并。Rxiv 原生 DOI+vN 独立保存，published 中的 NA 不是 DOI。原生 ID、DOI、明确发表关系建立 work_family，不用相似标题猜关系。各版本独立评估，最终最多推荐同一工作一次；journal_reference 或发表版 DOI 不证明当前预印本经过同行评审。

默认 preprint_venue_policy=separate：预印本 IF/JCR/WoS/CAS/CCF gate 标 not_applicable，正式论文仍执行开关；报告明示两个通道。若要求所有材料满足期刊评级，设 apply；要只看同行评审材料，设 peer_reviewed_only 或不含 preprint 类型。指定 journal_issns 限某期刊时，repository 适配器跳过并说明。机构表/EasyScholar 不向预印本仓库注入期刊评级。Q/M 量表相同，缺 IF 不扣质量分。
