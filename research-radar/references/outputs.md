# 宿主产物与固定编号

本协议 research-radar-harness-v1 由 agent 使用文件工具创建和核对，不需要解析器
或运行服务。文件系统不可写时在会话中展示等价内容，明确没有持久化；
新会话缺少原清单时让用户提供它，不能凭记忆重建编号。

每次检索使用独立 run ID 和目录。只保存脱敏后的需求与证据；不要复制完整私密配置。
推荐目录：

- preflight.md：本次有效需求、能力/服务状态、缺口与用户选择。
- search-log.md：实际查询、分页/引用动作、新增数、来源与停止原因。
- candidates.md：所有保留候选及排除/待核验理由和字段来源。
- reviews/：逐篇已阅读版本的证据和评审，使用随包模板。
- reading-list.md：面向用户的推荐与待评/待获取队列。
- selection-catalog.json：本清单固定的编号、身份、版本和推荐状态。
- downloads/manifest.md：第二步实际所选文件与校验结果，仅在下载时生成。

无需为未执行的步骤生成“已完成”空文件，不要求用户手工编写上述产物。

## 候选与评审

候选至少记录 ID、原始标题、作者、URL、DOI/原生 ID、发表类型、日期依据/精度、
来源、期刊身份/评级、版本与关系、概念/约束判断、获取状态。
每个冲突保留相应来源值，不静默覆盖。摘要、索引、出版社和真实全文分开标记。

逐篇评审绑定候选 ID、原始需求、实际材料版本/来源/获取方法/时间和身份锚点，
保留证据、主张审查、分项分数/缺口、有效分数限制与交付判断。
完整结构见 [review-template.md](../assets/review-template.md) 和
[质量协议](quality-evaluation.md)。换需求或版本后重新评审，旧报告不自动升级。

## 选择目录

以下仅是明确标注的虚构结构示例，不能作为真实检索结果：

```json
{
  "protocol": "research-radar-harness-v1",
  "run_id": "example-only",
  "created_at": "2026-10-15T00:00:00+00:00",
  "request": "Synthetic example, not a real search",
  "entries": [
    {
      "number": 1,
      "candidate_id": "source:synthetic-example",
      "title": "Synthetic example only",
      "url": "https://example.org/paper",
      "doi": null,
      "native_id": "synthetic-example",
      "publication_version": "preprint v2",
      "reading_version": null,
      "review_path": null,
      "recommendation": "pending_access",
      "quality": null,
      "match": null,
      "composite": null,
      "access": "unverified"
    }
  ]
}
```

固定编号是本 run 的标识，不随排序/显示子集改变。给定原始清单后不重写目录，
新增候选或重评发布新的 run/目录并注明关系。推荐集合不等于下载集合；
不能在目录里预填用户选择。用户选择可包含待获取但感兴趣的论文。

下载前核对目录与展示清单的编号、标题、ID/版本逐项一致，
去除重复选择并保留用户的精确集合。多个清单有相同编号时先确定 run。
编号选择对应目录中的版本；原版不可得时先让用户选择是否替换，
不自动换成另一稿件。评分只适用于实际读过的版本。
