# 数据字典

| 字段 | 类型 | 可空 | 定义 |
|---|---|---:|---|
| `run_id` | string | 否 | 输入摘要派生的稳定运行编号 |
| `batch_id` | string | 否 | 清单指纹 + `rule_version` + `path_rule_version` 派生的稳定批次编号 |
| `manifest_digest` | string | 否 | 清单有效行的规范化摘要，不含隔离行 |
| `snapshot_id` | string | 否 | 由快照对象元数据与两个规则版本派生的稳定编号 |
| `snapshot_digest` | string | 否 | 快照内容的完整摘要 |
| `collection_id` | string | 否 | 一次采集会话编号；中断后用同一编号续跑 |
| `cursor` | integer | 否 | 采集流中已消费的位置数；小于该位置的对象不再重读 |
| `source_line` | integer | 否 | 原文件物理行号 |
| `reason_code` | string | 是 | 隔离或冲突的稳定原因码 |
| `raw_value` | string | 是 | 未归一的原始证据 |
| `normalized_value` | string | 是 | 按项目规则得到的值 |
| `rule_version` | string | 否 | 计算规则版本，批次绑定时固定 |
| `path_rule_version` | string | 否 | 路径归一化规则版本，批次与快照均绑定 |
| `object_kind` | string | 否 | `file` / `directory-marker` / `empty-marker` |
| `status` | string | 否 | 逐项判定：`MATCH` `SIZE_MISMATCH` `ETAG_MISMATCH` `INVALID_VALUE` `MISSING` `DIRECTORY_MARKER` `EMPTY_PARTITION` `DUPLICATE_ROW` `DUPLICATE_CONFLICT` `ORPHAN` |
| `superseded` | array | 是 | 同名对象被覆盖前的 size/etag/kind，作为历史证据保留 |

字符串编号逐字保留。金额与计量值用 `Decimal`。时间值带偏移并以 UTC 参与比较。区间统一采用左闭右开。
