# 样例说明

除 `fingerprint.showcase.json` 为实测输出外，全部为 `authored-unvalidated` 的结构样例，数值与摘要为示意（`demo-*`），没有对应的真实素材、渲染或评审。用途是让 Schema、继承规则与相似度规则可以被程序检查。

| 文件 | 对象 |
|---|---|
| [material-profile.phone-review.json](material-profile.phone-review.json) | 8 分钟手机测评口播的素材画像（摘录） |
| [design-system.tech-redblack.json](design-system.tech-redblack.json) | 原创设计系统：技术看板·黑底红行 |
| [design-system.paper-highlighter.json](design-system.paper-highlighter.json) | 原创设计系统：纸感荧光·暖白纸底 |
| [component.spec-table.json](component.spec-table.json) | 组件：规格表（逐行点亮），含局部修改验收例 |
| [component.quote-giant.json](component.quote-giant.json) | 组件：巨幅引语 |
| [pack.speech-packaging-base.json](pack.speech-packaging-base.json) | 基础包：共用口播包装流水线（不可直接选用） |
| [pack.speech-spec-redline.json](pack.speech-spec-redline.json) | 皮肤包：红黑参数看板 |
| [pack.speech-bold-statement.json](pack.speech-bold-statement.json) | 皮肤包：观点大字 |
| [pack.speech-notebook-companion.json](pack.speech-notebook-companion.json) | 皮肤包：陪伴手记 |
| [pack.speech-editorial-magazine.json](pack.speech-editorial-magazine.json) | 机制包：黑白杂志专访（依赖主体遮罩） |
| [style-route-result.phone-review.json](style-route-result.phone-review.json) | 路由结果：稳妥 / 特色 / 反差三个方向 |
| [style-plan.phone-review.spec-redline.json](style-plan.phone-review.spec-redline.json) | 风格计划摘录：两个规格表实例与一个因间隔被丢弃的事件 |
| [fingerprint.showcase.json](fingerprint.showcase.json) | **实测**风格指纹：用 `tools/measure_fingerprint.py` 量本仓库 README 的演示片（19.6 秒、9 个镜头）。可测四轴区分不出风格包（`discrimination.verdict = low`），见 12 章 R2 |

检查：`python3 docs/multi-style/validate_examples.py`（需要 `jsonschema`）。它校验 Schema、皮肤包只覆写允许字段、皮肤包不新增必需能力、同基础包皮肤相似度 < 0.85。

包中引用的部分刻面（如 `cmp/value-callout`、`rhythm/tight-explainer`、`look/neutral-crisp`）尚未写样例文件，属于第一期待建清单。
