# 检索与匹配协议

## 研究问题

拆解研究对象、任务和用户要求的方法，组内列术语/缩写/复数，组间组合成完整 queries。方法不是用户要求时不要设成必须组。Crossref query 是相关性检索，不保证 Boolean AND；OpenAlex 独立 search 与结构化 filter 避免标点污染过滤式。

concept screening 保存 term/field，缩写按词边界匹配。review 模式缺词待核验：可能缺摘要或词表不全；strict_keyword 仅对有摘要的记录作显式词法排除。词法命中不证明论文方法用于目标任务，最终语义复核需指出具体联系。领域索引、受控词表和种子引文扩展用于补召回；源分页耗尽不代表系统综述查全。

## 期刊实体

resolve_journal.py 从 Crossref serial registry 解析名称/ISSN。唯一完整名称精确匹配或标识匹配才 resolved，模糊结果只供选择。曾用名/简称不可通过相似度自动等同。

验证 ISSN 校验位；保留印刷/电子/来源提供的 ISSN-L，不能猜测链接 ISSN。本地表每行索引所有标识。双方均有标识却无交集，即使刊名相同也 conflict。候选命中不相连的多个期刊实体是 conflict/ambiguous；用户提供的 aliases 可以精确查找，但无标识佐证仍 name_only。

journal_issns 使用 Crossref `filter=issn:...` 和 OpenAlex `filter=primary_location.source.issn:...`；多刊分别检索再 DOI 去重，结果复查标识。参见 [Crossref filters](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/) 和 [OpenAlex filters](https://help.openalex.org/api/filtering/)。

## 论文与指标

DOI 规范化优先去重；无 DOI 使用稳定 ID 或标题+首位作者+年，证据不足不按标题硬合并。不同 DOI 的同名文章不当作重复。source_records、field_provenance 保留字段来源；metadata_conflicts 阻止不透明覆盖。OpenAlex publication_date 不是首次在线日，保存为 published，online/print/issued 分开。

metrics 保存 value/source/source_url/retrieved_at/year/edition，以及 match_method/identity_verified/verified。API 读值、身份一致、来源核验、版次确认分别记录。EasyScholar documented officialRank/all、select 和 customRank 是评级观测，select 为账号选择的子集，文档不保证返回身份或年份；200 不能补成 verified。dataset_versions 来自用户，不证明官方当前版本。

本地表须显式 verified 和版本信息，WoS 可提供 checked_at。只有标识佐证身份的指标通过严格 gate。JCR 保存单版全部学科，默认最差分区过滤；同一学科矛盾或不同版次不混合。IF 两年/五年分开；中科院大类为默认值、小类独立保存；SCIE/SSCI/ESCI/AHCI 索引不从 IF/sci 字段推断；CCF 需版次与主会/分轨核验。

不明确的评级不是低质量，进入 needs_verification。各年份与冲突数值保留 observations；“最新版本”声明按 metric-freshness.md 另行核对。
