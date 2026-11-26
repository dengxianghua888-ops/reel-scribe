# 影述多风格优化方案：同一素材，做出不同风格的作品

2026 年 11 月 26 日 · 设计方案（未实现、未验收） · 收敛目标：剪辑 Agent

**一句话结论。** 把“风格”拆成可正交组合的刻面（剪辑方法、节奏、设计系统、组件、字幕、影调、声音、生成处理），由**风格包**声明哪些决定预先锁定、哪些按素材在运行时决定；**风格路由**按素材画像给出“稳妥 / 特色 / 反差”三个有差异的方向；**编译器**把选中的包装配成原子操作与渲染引擎的执行图；每个包上架前必须在盲评中**胜过定义好的默认基线**。这一切按剪辑 Agent 的对象设计，分三阶段从离线验证走到应用内置。

本方案只覆盖影述（剪辑侧）。生成侧（剧本选风格、风格圣经、即梦落地）在精品短剧仓库单独成文；两边的交换接口见 [11](11-interfaces.md)。

## 规模一览

| 对象 | 数量 |
|---|---|
| 场景 | 42 个，7 个领域 |
| 风格包 | 264 个（皮肤包 244、机制包 20），引用 218 张现有方法卡 |
| 设计系统 | 46 套，12 个视觉语言族 |
| 字幕样式 / 影调 / 声音 / 节奏 | 30 / 25 / 16 / 14 |
| 动效组件 | 126 个，16 类 |
| 渲染实现方式 | 14 种 |
| 公开调研来源 | 53 个，均固定提交并核对许可 |
| 基线 | 4 级：B0 行业技术、B1 默认（硬门槛）、B2 开源最佳、B3 人工专业 |

全部为设计条目（`catalog-draft`），数量不代表已验证的风格。

## 阅读顺序

| 章 | 回答什么 |
|---|---|
| [00 顶层设计](00-top-level.md) | 怎样收敛到剪辑 Agent：分层、对象映射、I0–I12 接口、三阶段路径、设计原则 |
| [01 诊断](01-diagnosis.md) | ChatCut 0.10.14 的风格体系怎样搭；影述还缺哪几层 |
| [02 公开仓库调研](02-public-survey.md) | 十类公开来源的结论、许可核对、合成出的体系骨架 |
| [03 场景 × 风格全景](03-scenario-style-catalog.md) | 42 个场景、264 个风格包怎样组织，怎样扩充而不平庸 |
| [04 动效组件体系](04-motion-components.md) | 效果优先、原子化；126 个组件、14 种实现方式与选择规则 |
| [05 风格路由](05-style-routing.md) | 从任务背景和素材得出适合的几种风格；多方向选取 |
| [06 风格包与装配](06-pack-assembly.md) | 刻面、决策槽、绑定规则；皮肤包与机制包；编译与降级 |
| [07 原子能力与协议增量](07-atomic-increments.md) | 新增原子、合同与 Work 模型的修改 |
| [08 同素材多风格样例](08-worked-examples.md) | 一条测评口播的四个包、一批商品实拍的三个包 |
| [09 基线、评测集与优质样本](09-baseline-eval.md) | 默认基线的精确定义、评测集、优质样本库、评审协议、放行门槛 |
| [10 路线图](10-roadmap.md) | 三期建设、放行条件、风险、需要拍板的决定 |
| [11 对外接口](11-interfaces.md) | 与剪辑 Agent、与生成侧的接口 |

## 机器可读部分

| 路径 | 内容 |
|---|---|
| [catalog/](catalog/) | 风格包、场景、刻面库、组件、调研表、覆盖统计（JSON 与 Markdown） |
| [tools/](tools/) | 目录数据与构建检查脚本：`python3 docs/multi-style/tools/build_catalog.py` |
| [schemas/](schemas/) | JSON Schema 草案：素材画像、刻面、风格包、路由结果、风格计划、交接、补镜、优质样本卡 |
| [examples/](examples/) | 可执行风格包、设计系统、组件、路由结果与风格计划的完整样例；`python3 docs/multi-style/validate_examples.py` |

## 与现有资产的关系

不推翻影述现有的作品版本、候选采用、范围授权、保护项、读回和能力交接合同。风格包最终编译为 `work-candidate/1`，经预览、审阅和 `work-version commit` 才算采用。现有 580 张风格卡成为方法刻面，[语义路由](../../registry/router.md) 继续负责选场景工作流。本目录不是 `contracts/package-members.json` 的发行成员，不改变任何现有原子或工作流的行为与验收状态。

研究依据：[ChatCut 0.10.14 图文报告](https://github.com/dengxianghua888-ops/editing-agent-research-library/blob/92b600d605b8bd8ed0e2c938c13561d3e66276e7/library-sync/followups/20261126-chatcut/report.md) · [口播与带货风格拆解](https://github.com/dengxianghua888-ops/editing-agent-research-library/blob/92b600d605b8bd8ed0e2c938c13561d3e66276e7/library-sync/followups/20261126-chatcut/2026-11-26-chatcut-0.10.14/%E7%9C%9F%E4%BA%BA%E5%8F%A3%E6%92%AD%E4%B8%8E%E5%B8%A6%E8%B4%A7%E9%A3%8E%E6%A0%BC%E6%8B%86%E8%A7%A3.md) · [桌面执行链与可编辑性](https://github.com/dengxianghua888-ops/editing-agent-research-library/blob/92b600d605b8bd8ed0e2c938c13561d3e66276e7/library-sync/followups/20261126-chatcut/2026-11-26-chatcut-0.10.14/REA%E5%88%86%E6%9E%90/ChatCut%E6%A1%8C%E9%9D%A2%E6%89%A7%E8%A1%8C%E9%93%BE%E4%B8%8E%E5%8F%AF%E7%BC%96%E8%BE%91%E6%80%A7.md) · [真人口播与实拍单品任务卡](https://github.com/dengxianghua888-ops/editing-agent-research-library/blob/92b600d605b8bd8ed0e2c938c13561d3e66276e7/library-sync/followups/20261126-chatcut/2026-11-26-chatcut-0.10.14/%E8%87%AA%E7%A0%94%E6%98%A0%E5%B0%84/%E7%9C%9F%E4%BA%BA%E5%8F%A3%E6%92%AD%E4%B8%8E%E5%AE%9E%E6%8B%8D%E5%8D%95%E5%93%81%E4%BB%BB%E5%8A%A1%E5%8D%A1.md)。
