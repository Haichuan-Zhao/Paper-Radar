# Candidate JSONL 与评审产物

每行一个 JSON 对象。未知值使用 null 或空对象，不虚构作者、日期、指标或质量分。
论文正文评审由 radar.py prepare-review/run 生成模板，使用 schema_version=5；
评分模型为 content-v4，详见 [scoring.md](scoring.md)。

## 候选记录

下面仅演示结构，不代表真实论文或评级。

```json
{
  "id": "doi:10.1234/synthetic",
  "doi": "10.1234/synthetic",
  "title": "Synthetic schema example",
  "abstract": null,
  "url": "https://doi.org/10.1234/synthetic",
  "authors": [],
  "publication_type": "journal-article",
  "published_online": null,
  "published_print": null,
  "version": null,
  "venue": {"name": "Example Journal", "issn": []},
  "metrics": {},
  "full_text_urls": [],
  "provenance": []
}
```

| 字段 | 约定 |
|---|---|
| id / doi | 正式论文优先规范化 DOI；无 DOI 保留来源 ID，不用近似标题自动合并 |
| preprint / version | 预印本原生 ID 和明确版本；已发表版本 DOI 只作关系，不覆盖预印本身份 |
| work_family / related_candidate_ids / relations | 只有原生 ID、DOI、来源明确关系才能关联；分别评价，最终最多推荐一个版本 |
| venue | 原始刊名、有效 ISSN/电子 ISSN/ISSN-L、出版社、卷期和需要的索引/会议 track 依据 |
| published_* / discovery.date_membership | 保存原始日期、精度、采用依据及 fallback；年份不能冒充具体日期 |
| metrics | 分别保存 value、source/source_url、edition、year、retrieved_at、verified 和 observations |
| full_text_urls | 来源所报 URL、版本、许可、格式及 OA 声明；链接不保证实际可读 |
| source_records / field_provenance / metadata_conflicts | 合并时保留各来源值、字段来源及冲突，不能用同 DOI 消除期刊身份冲突 |
| topic_match / journal_scope_match / venue_matches | 概念命中、明确限刊和期刊标识关联的审计结果 |
| filter | keep / needs_verification / exclude，以及逐条件 checks/reasons |
| preliminary | 仅相关性与时效的复核队列，不是科学质量分 |
| fulltext_access | 全文路线和实际宿主观察；获取状态不加减 Q/M/S |

期刊名一致但 ISSN 冲突时，阻止评级注入；仅刊名匹配的评级保持未核验。
verified=true 不能覆盖 identity_verified=false 或 conflict=true。IF 不证明 SCIE，
JCR 分区保留同一版次全部学科，默认严格过滤使用已列学科中最差分区。
出版类型与同行评审状态来自来源证据，不从期刊声望或标题猜测。

## 全文评审和结果

run 写入 review/review-packet.jsonl、reviews.template.jsonl、context.jsonl 和预算
清单。先看隐去作者/期刊的 packet，再按 [quality-evaluation.md](quality-evaluation.md)
阅读全文、看图、对比已有工作，另存完成的 reviews。

评审绑定 candidate_id、candidate_fingerprint、request_fingerprint、实际材料
ID/版本/来源、身份锚点、获取方式和检查时间。摘要只支持初判；仓库、图表和
全文锚点需对应实际核验来源。接受稿与正式版/预印本的绑定要求见
[fulltext-access.md](fulltext-access.md)。旧评审不能只修改 schema 数字后复用。

评审另需 claim_audit.coverage 与 claims，记录核心主张的作者原文、支持/限制证据、
适用范围和保守结论；优势、局限和阅读理由均为带 basis/claim_ids/evidence_ids 的
结构化对象。confirmed 缺陷需针对性 verification。完整字段与状态见
[质量协议](quality-evaluation.md)。这些结构化记录不构成自动科学真伪认证。

assess 写入 ranked.jsonl、reading-list.md、reviews.used.jsonl、
assessment-summary.json；包含 quality/match 的分项分数、综合优先级、理由、
局限、主张审查与分数约束、证据置信、未评/待获取队列。最终推荐以 selected_ids 为准。缺失为待评，
上下界是敏感性范围，不是统计置信区间。

如用户请求下载，实际核验 PDF 的身份、版本、签名与页数后才添加 pdf_path；
许可、来源、获取时间和 SHA-256 记录到下载 manifest。见
[download-and-zotero.md](download-and-zotero.md)。
