# 深度登记 对象存储清单与分区现存文件对账

        - 规模：中型
        - 核心规则：路径规范化后按 key、size 与摘要逐项比对，目录标记、空分区和缺失对象不得混为一类。
        - 使用者与工作流：导入随仓样例 → 批次采信清单 → 采集对象快照（可断点续跑）→ 按快照对账 → 导出单一证据清单。

        ## 批次、快照与规则版本

        一个批次由三件东西共同确定：清单指纹、计算规则版本 `rule_version` 和路径规则版本
        `path_rule_version`。三者任一变化就是一个新批次，重复导入同一组合得到同一个
        `batch_id`，不会新增记录。对象快照单独编号（`snapshot_id`），因此同一份清单可以
        绑定多个快照、各开一次对账：

        - `snapshots` 只在整批采集完成后一次性发布，发布后对象元数据不再改动。
        - `reconciliations` 以 `(batch_id, snapshot_id)` 唯一，重跑只取回原记录。
        - 没有快照的批次拒绝重算（`SNAPSHOT_MISSING`），不会拿现存文件冒充历史。
        - 复核旧批次读的是快照里登记的大小与摘要，而不是当前目录内容。

        ## 采集与失败语义

        - `POST /api/objects/verify` 带 `batch_id` 即进入批次采集；`max_records` 限制单次读取段长度。
        - 采集中断返回 409 `COLLECTION_INTERRUPTED`，已读对象与游标已落盘；带同一
          `collection_id` 重试即从断点续跑，`cursor` 之前的位置不再读取。
        - `simulate_write_failure=true` 模拟快照落盘失败：不发布半批、不登记对账，重试同幂。
        - 会话发布后拒绝继续追加（`COLLECTION_CLOSED`）；重复采集同一份对象流只会得到同一快照。

        ## 对账分类

        缺失必须分三类，不许混为一类：

        | 分类 | 判定依据 | 计数桶 |
        |---|---|---|
        | 匹配 / 大小或摘要冲突 | 同名文件存在 | `matched` / `conflicts` |
        | 缺失文件 | 同前缀无任何标记 | `missing` |
        | 目录标记 | 同前缀有 `_SUCCESS` 等提交标记 | `directory_markers` |
        | 空分区 | 同前缀有 `_EMPTY` 标记 | `empty_partitions` |
        | 重复行 | 归一化键在清单中重复 | `duplicates` |
        | 孤立对象 | 快照有、清单无 | `orphan` |

        守恒式：清单行数 = 匹配 + 冲突 + 缺失文件 + 目录标记 + 空分区 + 重复行，逐行
        `checks` 与导出 CSV 一一对应。

        ## 功能模块

        | 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
        |---|---|---|---|---|
        | M1 清单采信 | 导入清单并登记批次 | `/api/manifests/import` / `/manifest` / `/api/batches` | `app/modules/m1_manifest/core.py` `app/batches.py` | `tests/test_m1_manifest.py` `tests/test_m7_batches.py` |
| M2 路径契约 | 归一化路径与规则版本 | `/api/paths/normalize` / `/paths` | `app/modules/m2_paths/core.py` | `tests/test_m2_paths.py` |
| M3 对象核验 | 采集对象、发布快照、断点续跑 | `/api/objects/verify` / `/objects` | `app/modules/m3_objects/core.py` `app/objectmeta.py` | `tests/test_m3_objects.py` `tests/test_m7_batches.py` |
| M4 分区判定 | 运行样例并复核证据 | `/api/partitions` / `/partitions` | `app/modules/m4_partitions/core.py` | `tests/test_m4_partitions.py` |
| M5 差异对账 | 选批次与快照对账（当前/历史） | `/api/reconcile` / `/reconcile` / `/api/reconcile/history` | `app/modules/m5_reconcile/core.py` | `tests/test_m5_reconcile.py` `tests/test_m7_batches.py` |
| M6 批次导出 | 按批次/快照导出证据 | `/api/export/differences.csv` / `/runs` | `app/modules/m6_runs/core.py` | `tests/test_m6_runs.py` |

        ## 陷阱登记

        | TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
        |---|---|---|---|---|---|
        | TRAP-02 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m1_manifest/core.py` | `tests/test_m1_manifest.py::test_trap_1` |
| TRAP-05 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m2_paths/core.py` | `tests/test_m2_paths.py::test_trap_1` |
| TRAP-08 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m3_objects/core.py` | `tests/test_m3_objects.py::test_trap_1` |
| TRAP-09 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m4_partitions/core.py` | `tests/test_m4_partitions.py::test_trap_1` |
| TRAP-14 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m5_reconcile/core.py` | `tests/test_m5_reconcile.py::test_trap_1` |
| TRAP-16 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m6_runs/core.py` | `tests/test_m6_runs.py::test_trap_1` |
| TRAP-18 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m1_manifest/core.py` | `tests/test_m1_manifest.py::test_trap_2` |
| TRAP-21 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m2_paths/core.py` | `tests/test_m2_paths.py::test_trap_2` |
| TRAP-22 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m3_objects/core.py` | `tests/test_m3_objects.py::test_trap_2` |
| TRAP-23 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m4_partitions/core.py` | `tests/test_m4_partitions.py::test_trap_2` |

        ## 对账规则

        - 输入记录数 = 有效记录数 + 隔离记录数 + 空记录数。
        - 核心数值或事件数在转换、判定和导出之间保持守恒。
        - 同一输入摘要重跑复用原运行编号，不增加结果行。
        - 同一(批次, 快照)的对账只登记一次，重跑复用原 `reconciliation_id`。
        - 缺少快照的批次不参与重算；历史结论不改写，新差异由新快照承载。

        ## 已知不覆盖

        - 生产系统连接、身份认证和外部密钥不在演示范围内。
