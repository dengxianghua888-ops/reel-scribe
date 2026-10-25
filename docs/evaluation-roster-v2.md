# 评测名册版本与剧情试点

汇总器计算已给审查行的数值，不评价剧情、不自动打分、不证明审查者独立，也不决定发布。

`evaluation-roster/1` 保持 W01–W16 的原规则，包括 180 例分配门槛、旧分母、缺失样本处理、指标和输出格式。新增 W17 不回写旧报告，也不向旧名册加入一个零样本包。

新范围使用 `evaluation-roster/2`，必须明确 `package_ids` 与 `evaluation_scope`。其他案例字段及 runs/scores 的格式继续沿用 `/1`；runs/scores 必须绑定完整名册的实际 SHA256。

```json
{
  "schema": "evaluation-roster/2",
  "revision": "drama-pilot-01",
  "evidence_class": "synthetic-harness-check",
  "package_ids": ["W17"],
  "evaluation_scope": "declared-package-pilot",
  "cases": [
    {
      "case_id": "drama-fixture-01",
      "family_id": "declared-story-state",
      "stratum": "package",
      "work_package": "W17",
      "in_declared_scope": true,
      "full_production": false,
      "critical": true
    }
  ]
}
```

这个示例只定义名册形状，尚无运行或分数。剧情校验器的 22 例也不能自动变成内容效果分数；需要先将每例的实际范围、运行与审查结论写成对应记录。

| evaluation_scope | 适用情况 | 分配门槛与报告 |
|---|---|---|
| `declared-package-pilot` | W17 或明确子集的局部试点 | 只统计声明的包；库级 `initial_allocation_floor_met=null`、`allocation_floor_applicable=false`，不声称全库验收 |
| `full-library` | 新版全部 W01–W17 | 必须声明全部 17 包；每包至少 8 例，shared-atomic 20、cross-package 16、revision-recovery 8、failure-outside 8，共至少 188 例 |

包名单必须非空、无重复且为已知 W01–W17。每例只能使用声明包，非 package stratum 仍可用 null。新包未运行时保留 NOT_RUN；不补分、不删除失败样本。名册声明和实际病例配额是两项检查，声明一个包不代表它已有样本。

新名册输出 `evaluation-summary/2`，增加声明范围与门槛适用性；旧名册继续输出原 `/1`，未新增字段。所有版本的 `release_accepted` 都保持 false，由独立验收决定是否可交付。

兼容测试以基线 `0288db1a7c9ec3cbeb77673d5cf18279385c2340` 的原汇总器为依据：完整 180 例与缺运行/缺评分两组固定合成输入，对比整个规范 JSON 报告的 SHA256；同时校验新名单、缺项、W17 范围和 NOT_RUN 不计通过。此证据仅证明汇总兼容，不能证明 180 个真实制作任务成功。
