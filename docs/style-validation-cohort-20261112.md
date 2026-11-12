# 首批九张风格卡：机制证据分层，不改全库状态

基线：PR #23 远端 `8c4da2ada780d1a278146c44d990e9b8f4d3ee6c`，本地 `f259b445f69cf912ac8c799019f1ed9c488cd2ea`；相同 tree `45790f7676abef0fe2c103aef99dd584b0e463cf`。这是候选分支，不是已发布产品。本轮逐张读了下列九卡正文；未逐读全库580卡，不修改卡片/catalog原有 authored-unvalidated 状态。

## 分级规则

- **authored**：已有具体适用、机制、反例与检查方法；不是实测。
- **contract-tested**：对应有限代码机制有约束/失败用例；不代表卡的审美、语义或叙事全部实现。通用机制只有“可支撑”关系时，不升级卡本身。
- **real-media-mechanism**：卡的特定机制实际用于可追溯真实素材，有输出与有限观察；必须逐项写明观察范围，不能借用其他卡的实验。
- **whole-style-validated**：本卡完整适用场景、核心效果、保真及必要看听/用户任务证据成立。**本轮九卡没有任何一张达到此级。** 这不是额外统一发布门槛，而是避免把机制与整体风格混为一谈。

## 九卡实际内容、可执行能力和缺口

| 卡片 | 正文主张与关键反例 | 当前证据等级（仅本轮） | 代码/证据映射 | 下一最小有区分力验证 |
|---|---|---|---|---|
| [结果先行适配](../styles/reference/consequence-first.md) | 真结果→过程→限制；必须标回看，不能借别的成功画面冒充 | **real-media-mechanism，严格限结果预览** | `runtime/result_preview_ops.py`固定此卡身份、同源结果窗、全原流程后移授权、显式非当前成功标签；22项契约测试。真实wikEd原24–64s流程，前置后段4s得到44s候选；已看2s/5s标签及UI，原40s流程保留 | 比较原版/候选完整看听，核预览是否诱发“已完成”的误解；当前无真实参考片观察，不能称迁移复刻或因果验证 |
| [分维度融合](../styles/reference/axis-separated.md) | A叙事+B声音+C文字，按维度分工，不能三种风格全强度叠加 | **authored；通用隔离合同可支撑** | `style_recipe_ops.py`将字号/颜色/边距/固定音轨增益与内容分开；`revision_impact.py`分依赖。但没有此卡的多参考分工执行 | 选两个有实际观察证据的参考，每个只负责一维，逐项采纳/替代/舍弃；不要拿同一视频改两个字号冒充多参考融合 |
| [局部采用](../styles/reference/local-adoption.md) | 只改选区及衔接，无关音轨冻结；反例是改开头却全片换字幕 | **authored；通用scope合同可支撑** | Work scope/冻结/CAS测试与真实短窗恢复已有证据，未见本卡特定局部参考迁移。当前全局caption_style不支持只改某一句字体 | 用两个段落，授权首段显式切点，锁后段及独立音轨；验证越界失败、恢复保留后续手改。若需局部字幕样式，先标现接口不支持 |
| [忠实轻剪](../styles/speech/faithful-clean.md) | 只清口误/放弃残句，保留气口、否定、人物语气；反例为词表式删“其实/然后” | **authored；呈现参数实验不升级此卡** | 配方可绑定卡身份，Work/证据保护可限制修改；FLEURS只是文字/画布技术验证，没有真实剪词听检 | 找同一说话人含否定与强调重复的许可短段，明确词界来源；对照仅填充删除与误删否定的拒绝/恢复。没有听审不标忠实轻剪通过 |
| [证据解释](../styles/speech/evidence-led.md) | 问题→口径→证据→解释→限制；保留“大约/可能”、数值单位；相关性不能剪成因果 | **authored；证据映射合同可支撑** | evidence-map保声明源窗及依赖；benchmark明确单次与未知费用是报告纪律，不是本卡口播成片证据 | 真实带数值/限定语片段，声明必须保留单元；比较压缩前后观点强度。接口只能检查声明，漏声明的限定仍需回源 |
| [证据型产品演示](../styles/software/evidence-demo.md) | 同案例输入→执行→结果→产物检查；反例为队列开始当完成 | **authored；教程proof机制可支撑** | `tutorial_ops.py`检查声明before/action/result时窗和依赖；结果预览候选保完整流程，但绑定的是consequence-first，不能继承为本卡验收 | 在同一真实任务中确认产物打开/保存证据，加入“提前成功字幕”负例；核操作证据本身，不依赖漂亮状态计数器 |
| [阅读优先教学](../styles/software/readable-deliberate.md) | 留定位、读字段、操作、核对；字幕避内容，不能以慢放补模糊 | **authored；真实排版机制是邻近证据，不升级此卡** | `caption_layout.py`真实alpha覆盖+保护区；960×636/24px独立黑带抽帧改善，但实际绑定guided-first-run而非此卡，且未测字段阅读完成 | 同一文本密集操作片，维持内容/音量，仅改变必要阅读窗口；目标尺寸可读与能否完成核对需实际观察，覆盖PASS不能代替 |
| [首次上手带练](../styles/software/guided-first-run.md) | 入口→必要设置→依赖操作→成功反馈；反例为省前置设置却声称零基础会用 | **contract-tested/有限真实呈现子机制，不是完整风格** | 真实字幕带recipe确绑定此卡SHA；24px字幕在独立黑带的alpha与抽帧可复核。只执行文字包装，未执行入口选择/步骤编号/成功反馈教学机制，因此不升为整卡real-media-mechanism | 真实新手任务完整入口/设置/保存重开，依据用户能否指出成功反馈；当前实验仅支持不遮挡与标签显示结论 |
| [因果主线](../styles/film-recap/causal-spine.md) | 目标→行动→选择→代价；反例为相邻事件写成因果、虚构内心 | **authored；R0/R1合成联合组可支撑** | R0/R1动作A+反应B金标/四层失败测试是合成；电影真实短窗/宿主剪切未验证人物动机和因果 | 从许可电影建立一个动作+反应联合组及误导对照，人工标明事实/推断；比较池、计划、实际消费。没有真实成片看听不标因果保真 |

## 字节身份

全部为0.1.0卡内容。下列SHA仅绑定本次读到的文本，不是能力认证：

```text
reference/consequence-first.md f0113143fe127279fdf3733db7dddf3a7dff998240c1b53128234fa2ed6c7502
reference/axis-separated.md b8418235e6946b8db0c2ff2f586ace19f5158d3da953b923c4e3eaae32613883
reference/local-adoption.md 02d0bd50e16c3ad5b7e4cabf1aa9f2f732b2ef9abb1739f1561df19fd4b12f8e
speech/faithful-clean.md 7cd361368644fd7d20c572a8012d444e0d0ba7a07df0af3ccbd8635843659709
speech/evidence-led.md 60735e685fedf04635702ba6897065ea8a78da07244333d24d50deb077bc26da
software/evidence-demo.md d18d6d57a8c2ead5f63fea56565194fa790f1cec7f8c80fc7ea5b5da788302c9
software/readable-deliberate.md c6913f938d82ba2b70f7c2d2f4372eab7f8f575c38ec96cec11e2a4d07533ec8
software/guided-first-run.md 943bb3653f347a554a940099b8b83ca2b39c1628ece3ee1571cf9fbf6cb71503
film-recap/causal-spine.md 1dca91bd5b0bcecb8a13856b1ae56aea944c12f8b5352c274f9051aa9e265584
```

真实媒体归属/许可及有限观察见[本轮迭代](product-iteration-20261112.md)、[结果预览合同](../contracts/result-preview-contract.md)、[呈现配方合同](../contracts/style-recipe-contract.md)。原视频不随本清单分发，未分发证据不冒充可在线下载复现。未读取历史本地归档引用，不据69条旧引用升级状态。

## 下一项：真实教程“前置结果”与持久证据保护共同成立

**建议优先在现有result-preview基础上支持最小、明确授权的教程证据映射，而不是新增更多风格卡。** 现入口遇到任何持久evidence_protection就拒绝，这是正确安全边界，但阻止“原过程已锁定→只添加明确后段预览”的有价值任务。最小实现只支持原clips不改、全部恒速、无独立音轨/视觉层、追加前置preview且显式scope.evidence_mapping；原units/requires/required_units不删不改，原occurrences仍指向原carrier，原段后移后重新编译并验证。新预览不得自动充当旧依赖的证据occurrence，不得把预览当当前步骤成功。无法证明的保护继续拒绝，不引导用户关保护。

可立即复用已有44秒wikEd实验：基线原40秒保留before/action/result单位，新增4秒标记预览；应通过原单元连续覆盖与先后关系。故障例：删原动作只剩预览、将原result依赖指向预览、减少required_units、错源、过期头、未授权映射均应拒绝。对照实际输出原流程源窗与声画数值并抽帧标签；完整看听仍单列未验。这样同时推进consequence-first、local-adoption、evidence-demo的**不同机制证据**，但仍不自动使三卡整体通过。

**接续状态（同日，待集成新SHA）：** 上述最小保护共存提案已实现并完成33项定向测试及真实44秒评估副本编译/渲染；详见[保护共存验收](result-preview-protection-20261112.md)。这推进有限机制，不改变本表九卡whole-style未验收的结论。下一独立优先项转为真实中文否定保护/误删拒绝/恢复与明确看听边界，而不是重复实施本提案。
