# 多风格体系设计：同一素材，做出不同风格的作品

2026 年 11 月 26 日 · 设计方案（未实现、未验收） · 适用：影述 Reel Scribe（剪辑侧）＋ 精品 AI 短剧 Skill（生成侧）

**一句话结论。** 把“风格”从一张写满判断的说明卡，拆成**可正交组合的刻面**（剪辑方法、节奏、视觉设计系统、可编辑组件、字幕、影调、声音、生成处理），由**风格包**声明哪些决定预先锁定、哪些按本次素材在运行时决定，再由**风格路由**根据素材画像给出“稳妥 / 特色 / 反差”三个有差异的方向，最后由**编译器**把选中的包装配成现有原子操作的执行图。同一条口播、同一批商品实拍、同一份剧本，因此能稳定地产出多种风格，且每种都可追溯、可局部改、可横向比较。

本目录写剪辑侧与两仓共享协议；生成侧（剧本选风格、风格圣经、反平庸、即梦落地）见短剧仓库的[多风格导演体系](https://github.com/dengxianghua888-ops/premium-ai-short-drama-skill/blob/claude/multi-style-content-generation-6gvie3/%E6%96%B9%E6%A1%88/%E5%A4%9A%E9%A3%8E%E6%A0%BC%E5%AF%BC%E6%BC%94%E4%BD%93%E7%B3%BB/README.md)。

## 阅读顺序

| 章 | 回答什么问题 |
|---|---|
| [01 诊断与借鉴](01-diagnosis.md) | ChatCut 0.10.14 的风格体系到底怎么搭；影述与短剧 Skill 现在缺哪几层 |
| [02 顶层架构](02-architecture.md) | 八层模型、九条设计原则、对象之间的关系 |
| [03 风格路由](03-style-routing.md) | 怎样从任务背景和素材得出“适合哪几种风格”，怎样避免只推荐最平均的一种 |
| [04 风格包与原子装配](04-style-pack-assembly.md) | 一个风格主题怎样组装、调配原子能力；皮肤包与机制包的成本差 |
| [05 原子能力与协议增量](05-atomic-increments.md) | 新增哪些原子、改哪些合同、Work 模型加什么字段 |
| [06 同素材多风格样例](06-worked-examples.md) | 同一条手机测评口播的四个风格包，同一批商品实拍的三个风格包，逐项看差异落在哪里 |
| [07 两仓互补](07-cross-repo.md) | 生成侧与剪辑侧的边界、交接协议、三条联动链路 |
| [08 审美门、评测与路线图](08-taste-eval-roadmap.md) | “不平庸”怎样落成可检查的门槛；指标；分三期的建设顺序与放行条件 |

机器可读草案：[schemas/](schemas/)（JSON Schema 2020-12）与 [examples/](examples/)（风格包、设计系统、组件、素材画像样例）。样例均为 `authored-unvalidated`，只说明结构，不代表已出片。

## 十条关键设计决定

1. **先问素材起点，再问风格。** 入口先分“已有素材→剪辑工程 / 缺画面→生成 / 只有主题或商品→混合成片 / 只要方案”，再在该路线内选风格。不同起点的返工单位不同，入口要提前说清。
2. **风格是刻面组合，不是一个形容词。** 至少拆出 8 个刻面，各自独立注册、独立版本、独立验收。“科技感”必须落成“讲到参数时点亮规格表对应行”这样的可执行规则。
3. **锁定决定与运行时决定显式分开。** 风格包声明 `locked`（选卡即定）、`runtime`（读完素材再定）、`user`（必须问用户）三类决策槽；Agent 只能在 `runtime` 槽里发挥。
4. **皮肤包复用流水线，机制包新增能力。** 换设计系统即可得到的新风格（ChatCut 11 张口播包装中的 8 张）只算皮肤；需要跟踪、分割、转绘的风格要先建原子能力，再谈上架。
5. **触发规则把内容信号接到组件实例。** 素材画像抽出“数值、步骤、引语、转折、情绪峰”等带词级时间的信号；风格包的绑定规则把信号映射为组件实例、出现时机、版位与密度上限。
6. **多方向推荐，而不是单点最优。** 路由先做资格过滤，再打适配分，最后用最大边际相关（MMR）取出“稳妥 / 特色 / 反差”三个方向，每个都附素材证据和代价。
7. **用真实素材预览，在昂贵步骤前选。** 先出文字方案对照，再出风格帧，再出 10–15 秒样段，最后才全片渲染或提交生成。
8. **事实与保护优先于风格。** 任何风格包都不能删除受保护的限定、数值单位、否定和证据镜头；风格只决定“怎样呈现”，不决定“说了什么”。
9. **“不平庸”是一道门，不是一句口号。** 每个包必须声明签名手法、克制规则和俗套黑名单；成片要在盲评中胜过“默认参数基线”才可标记风格有效。
10. **卡数不是能力。** 风格包按 `authored → compiled → previewed → limited-trial → validated` 分级，货架只展示达到门槛的包；580 张现有方法卡继续作为方法刻面使用，不计作“580 种风格”。

## 与现有资产的关系

本方案不推翻影述现有的作品版本、候选采用、范围授权、保护项、读回和能力交接合同，所有新对象都落在 [Work 合同](../../contracts/work-contract.md)、[风格配方合同](../../contracts/style-recipe-contract.md) 与 [能力交接合同](../../contracts/capability-handoff.md) 之上：风格包最终编译为 `work-candidate/1`，经预览、人工审阅和 `work-version commit` 才算采用。现有 [风格卡](../../styles/speech/index.md) 成为“方法刻面”，[语义路由](../../registry/router.md) 继续负责选场景工作流，新增的风格路由只在工作流内部选风格包。

研究依据：[ChatCut 0.10.14 图文报告](https://github.com/dengxianghua888-ops/editing-agent-research-library/blob/92b600d605b8bd8ed0e2c938c13561d3e66276e7/library-sync/followups/20261126-chatcut/report.md) · [口播与带货风格拆解](https://github.com/dengxianghua888-ops/editing-agent-research-library/blob/92b600d605b8bd8ed0e2c938c13561d3e66276e7/library-sync/followups/20261126-chatcut/2026-11-26-chatcut-0.10.14/%E7%9C%9F%E4%BA%BA%E5%8F%A3%E6%92%AD%E4%B8%8E%E5%B8%A6%E8%B4%A7%E9%A3%8E%E6%A0%BC%E6%8B%86%E8%A7%A3.md) · [桌面执行链与可编辑性](https://github.com/dengxianghua888-ops/editing-agent-research-library/blob/92b600d605b8bd8ed0e2c938c13561d3e66276e7/library-sync/followups/20261126-chatcut/2026-11-26-chatcut-0.10.14/REA%E5%88%86%E6%9E%90/ChatCut%E6%A1%8C%E9%9D%A2%E6%89%A7%E8%A1%8C%E9%93%BE%E4%B8%8E%E5%8F%AF%E7%BC%96%E8%BE%91%E6%80%A7.md) · [口播与带货建设判断](https://github.com/dengxianghua888-ops/editing-agent-research-library/blob/92b600d605b8bd8ed0e2c938c13561d3e66276e7/library-sync/followups/20261126-chatcut/2026-11-26-chatcut-0.10.14/%E8%87%AA%E7%A0%94%E6%98%A0%E5%B0%84/%E5%8F%A3%E6%92%AD%E4%B8%8E%E5%B8%A6%E8%B4%A7%E5%BB%BA%E8%AE%BE%E5%88%A4%E6%96%AD.md) · [0.10.12 产品拆解](https://github.com/dengxianghua888-ops/editing-agent-research-library/blob/92b600d605b8bd8ed0e2c938c13561d3e66276e7/library-sync/followups/20261126-chatcut/2026-11-25-chatcut-0.10.12/%E4%BA%A7%E5%93%81%E5%88%86%E6%9E%90/ChatCut%E4%BA%A7%E5%93%81%E6%8B%86%E8%A7%A3.md)。

本目录是设计稿，不是 `contracts/package-members.json` 的发行成员，不改变任何现有原子或工作流的行为与验收状态。
