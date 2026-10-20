# 最小持久化约定

协议 paper-radar-v2。每次 run 放在配置旁 paper-radar-results/<run-id>/，自定义目录优先。
需要时才建产物；同一内容保留一份，其他文件引用它。无文件系统时交付等价会话记录。

| 文件 | 保存什么 |
|---|---|
| RADAR.md | 顶部当前进展；下方逐轮实际工作和恢复位置 |
| candidates.md | 广泛候选、逐字段来源、版本关系、筛选/待核验理由 |
| papers/<candidate-id>.md | 该版本的原始证据、主张检查与逐篇评审 |
| reading-list.md | 第一步的固定编号推荐、待评队列、排除与覆盖 |
| selection-catalog.json | 与该清单一致的编号/身份/版本/状态，发布后不覆盖旧修订 |
| downloads/manifest.md | 第二步实际文件与验证结果；正文存入用户下载目录 |

稳定 candidate ID 与排序号分开；缓存/PDF/凭据不重复塞入报告。
材料引用可回访来源或实际缓存，标明获取时间、版本和修订；不伪称保存了快照或哈希。

## RADAR.md

顶部保存 run ID、用户原话、日期/硬约束/软偏好/目的、配置路径（无私密值）、
评分版次、实际能力/协作限制、已接受缺项、预算与耗用、已有认识/分歧、计数、
状态、目录修订、下一步及精确恢复位置。状态可为 searching/checking/reviewing/
awaiting_selection/partial/paused/blocked/downloaded。

下方按 R001、R002 保留历史：先写问题/计划；实际执行后写工具/查询/页或引文路径、
原始返回和去重新增、来源位置、失败/未执行、固定材料、真实角色与所审范围、
原核验/评审意见、补证决定、耗用和交接。计划不冒充执行，不重复抄逐篇分项。

## 逐篇记录

- 身份/版本：原题名、作者、DOI/原生 ID、发表日期与阅读版本、全文/图表范围、获取状态。
- E-ID：类型、原始来源 URL/文件、页/节/图/表/公式、短原文或实际观察、时间、材料修订。
- C-ID：作者主张与位置、是否核心/角色、不同位置的支持与限制 E-ID、结论、适用范围、
  核查方法及未排除解释。findings 保留 severity、suspected/confirmed 与验证证据。
- 硬约束逐项 pass/fail/unknown；每个 Q/M 分项保存 0–5/null、理由和证据，
  M 同时引用需求锚点。保存原始值、上限后有效值、Q/M/α/S、算术与门槛复核。
- reviewer_assessment 与 author_report 分开；保存优势、局限、迁移条件、推荐/待评理由、
  review_confidence 和 self_check/independent/limited、实际角色 ID/上下文与所查范围。

## 第一步清单与固定目录

清单说明 run/目录修订、原始问题、日期依据、约束、接受的限制、预算、真实来源与
查询/分页/引用范围、计数和未完成分支。每篇给固定编号、原题名/链接、版本/日期、
Q/M/S 或待评、评级来源/版次/年份、匹配理由、保守结论、局限和实际获取状态。
分开推荐与待获取/待评/待核验；记录重要排除及分歧，不用待评条目凑高质量篇数。

目录结构示例（虚构，不是研究结果）：

```json
{
  "protocol": "paper-radar-v2",
  "run_id": "synthetic-only",
  "catalog_revision": 1,
  "request": "Synthetic example",
  "entries": [{
    "number": 1, "candidate_id": "synthetic:A", "title": "Synthetic paper A",
    "url": null, "doi": null, "native_id": "synthetic:A",
    "publication_version": "preprint v2", "reading_version": null,
    "review_revision": null, "recommendation": "pending_access",
    "quality": null, "match": null, "composite": null,
    "fact_check": "unverified", "review_mode": "self_check", "access": "unverified"
  }]
}
```

发布前核对清单与目录逐项一致；后续显示子集/重排不改编号，不预填用户选择。
发布后改变评审或新增候选另存目录修订。用户选“第 1、3 篇”时解析原 run/修订，
只有歧义才澄清，不凭记忆重建。“全部推荐”不包括待评队列。
第二步 manifest 字段与验证要求见 [access.md](access.md)。
