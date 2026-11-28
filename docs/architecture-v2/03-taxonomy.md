# 03 Skill、场景与工具的划分

“Skill 该拆多细”混了三种粒度：知识按场景定，执行按可测单元定，模型可见面按任务类定。影述现在的问题是把执行粒度原样搬到了知识层（每个原子一份说明，加一份要求通读的路由），模型可见面却只有一个通用入口。本章把资产分成八类，每类写明定义、谁消费、何时加载、怎样测、怎样升级。

## 一、八类资产

| 类 | 是什么 | 例子 | 何时进入模型上下文 | 主要测试 | 不该放什么 |
| --- | --- | --- | --- | --- | --- |
| A 入口硬规则 | 每次都必须遵守的十几条规则 | 冻结与否定约束优先；仅分析不渲染；参数齐全直调；缺关键对象先问 | 常驻 | 路由评测集上的违规率 | 领域细节、相邻歧义的长篇说明 |
| B 场景卡 | 一类稳定、高频的交付怎样完成：判断要点、退出条件、产物依赖 | 口播精剪、局部修订、访谈多机位、商品故事、AI 短剧导演 | 指定或检索命中后加载 | 有无配对；指定组与自选组 | 参数细节、工具用法 |
| C 方法卡 | 可跨场景复用的一个判断方法 | 辨认视线、证据解释、保真清理、按用途取段 | 检索命中后只读命中部分 | Oracle / Auto / None 三组 | 绑定某个场景的流程 |
| D 风格数据 | 刻面、设计系统、风格包、俗套清单 | 多风格目录的 264 个包、580 张风格卡 | 不进上下文；由 `style.route` 读取 | G0–G3 门；分层评测 | 判断方法（应写成方法卡） |
| E 工具组 | 模型可见的带类型操作，每组 4–10 个，附说明与下钻 | `edit.*`、`style.*`、`gen.*` | 工具定义按需检索 | 接口阶梯；pass^k；调用数 | 内部步骤、哈希搬运 |
| F 编译器与原子执行单元 | 程序内部的确定性单元 | 51 个现有原子、19 个新增原子、各 `*-compile` | 不进上下文 | 单元测试、黄金帧、属性等价 | 任何需要判断的选择 |
| G 检查器与评审器 | 程序硬门、校准过的模型评审、人评协议 | `media-qc`、色彩门禁、合规门、`taste-review` | 评审器在独立上下文 | 与人工标签的一致率 | 直接写工程的能力 |
| H 数据契约 | 跨层、跨仓的 Schema | `task-spec/1`、`evidence-record/1`、`edit-intent/1`、`write-receipt/1`、三份交换文件 | 按需 | Schema 校验与往返测试 | — |

B 和 C 是“Skill”的本义：保存方法。E 和 F 是“能力”：一个给模型调用，一个给程序调用。D 是数据，交给程序读。把这四类分开存放、分开测，是 v2 的核心变化。

## 二、新需求来了，放哪一层？

按顺序回答四个问题。

| 顺序 | 问题 | 回答“是” | 回答“否” |
| --- | --- | --- | --- |
| 1 | 完成它需要判断吗（重要性、情绪、风格、故事、适合）？ | 去问题 2 | 参数齐全的执行：已有工具组能表达就直接用；不能表达就新增 F 类原子，并在高频时为它开一个 E 类组合入口 |
| 2 | 这个判断能独立取证、交给别人独立核对吗？ | 交给只读取证助手（L2）或 G 类检查器，交回证据记录 | 留给主 Agent，去问题 3 |
| 3 | 换一个用户目的，这个判断方法还值得复用吗？ | 写成 C 类方法卡 | 写进对应的 B 类场景卡 |
| 4 | 它是外观、包装上可以枚举的选择吗？ | 写成 D 类风格数据（刻面、设计系统、风格包） | 维持在 B 或 C |

新资产进入任何一类之后，状态都从 `draft` 起步，只有过了[05](05-metrics-experiments.md)对应的测量，才能进入路由池或货架。

## 三、现有 17 条场景工作流的去留

阶段 1 只让少数场景卡处于“活跃”状态，其余保留文档、退出默认路由池，直到有测量支持。依据是研究库确定的建设顺序（先口播精剪与实拍单品），以及多风格方案的 P0 场景。

| 场景工作流 | v2 状态 | 理由 |
| --- | --- | --- |
| `raven-speech-edit` 口播 | 活跃（阶段 1 纵切） | 研究库首个建设方向；有 `speech-plan-compile` 与 `zh-cut-truth` 可测 |
| `raven-local-revision` 局部修订 | 活跃（阶段 1 纵切） | 用户信任的关键；等长替换是组合入口的首个样例 |
| `raven-commerce-story` 商品故事 | 活跃（阶段 2） | 研究库第二个方向；主张—证据表可程序核对 |
| `raven-drama-production` 剧情制作 | 合并 | 与精品短剧 Skill 合并为“导演手册在短剧仓、执行在影述工具组”，见短剧仓库《12 迭代方案 v2》 |
| `raven-film-recap` 影视解说 | 隔离 | 自带 13 阶段代码流水线与独立状态；保留现状，阶段 3 前迁到通用 Work |
| `raven-interview-multicam`、`raven-software-tutorial`、`raven-course-meeting` | 休眠 | 文档保留；进入路由池前先做有无配对 |
| 其余 9 条 | 休眠 | 同上 |

“休眠”不删除文件。休眠场景在路由时不参与召回；用户在界面上显式选中时仍可加载，并在任务单里标 `scenario_status: dormant`。

## 四、模型可见的工具组

### 1. 设计规则

- **按任务类分组，每组 4–10 个操作。** 每组另有 `describe`，返回某个操作的完整参数说明与例子。
- **为高频组合开口。** 局部修订最常见的“等长替换”“改稿并预览”“局部撤销”各有一个入口。
- **程序持有机械信息。** 哈希、版本令牌、绝对路径、工作目录由运行时持有，模型只引用对象 ID。
- **错误可行动。** 拒绝时返回冲突约束与可放宽项，而不是一句“请求无效”。
- **读写分组。** 取证助手只拿到读取组；写入组只给主 Agent。

### 2. 十组工具

| 工具组 | 读/写 | 操作（示意） | 后端（现有或新增） |
| --- | --- | --- | --- |
| `work.*` | 读 + 撤销 | `read`、`history`、`diff`、`receipts`、`undo_edit`、`describe` | `work-version`、`revision-impact-inspect`、`prepare-local-undo` |
| `media.*` | 读 | `inspect`、`frames`、`audio_slice`、`signals`、`profile`、`describe` | `media-inspect`、`frame-extract`、`audio-extract`、`media-signal-scan`、`sync-offset-measure`、新增画像三件套 |
| `transcript.*` | 读 | `transcribe`、`import`、`compare`、`signals`、`describe` | `speech-transcribe-local`、`transcript-import`、`transcript-reference-compare`、新增 `content-signal-extract` |
| `evidence.*` | 读 | `search`（按人物、视线、动作、声音检索素材索引）、`claims`、`bind`、`describe` | `evidence-plan-compile`；素材索引为新增 |
| `edit.*` | 写 | `propose`（接受 `edit-intent/1`）、`replace_same_length`、`trim_words`、`commit`、`discard`、`describe` | `timeline-patch`、`timeline-revise`、各 `*-plan-compile`、`work-version commit` |
| `style.*` | 读 + 生成候选 | `route`、`preview`、`plan`、`set_component_props`、`describe` | 新增 `style-route`、`design-token-resolve`、`style-pack-compile`、`multi-style-preview` |
| `look.*` | 生成候选 | `scan`、`fit_reference`、`grade`、`consistency`、`describe` | 色彩 10 个原子 |
| `audio.*` | 生成候选 | `mix`、`envelope`、`loudness`、`describe` | `audio-mix`、`audio-envelope`、新增 `sound-event-place` |
| `render.*` | 读 + 导出 | `preview`、`preview_pair`、`export`、`qc`、`describe` | `work-render`、`result-preview-compile`、`media-qc` |
| `gen.*` | 写（花钱） | `preflight`、`submit`、`status`、`ledger`、`adopt`、`describe` | `generation-task`；`preflight` 为新增 |
| `review.*` | 读 | `check`（程序硬门）、`prescreen`（模型预筛）、`blind_task`（生成盲评任务） | `media-qc`、`style-conformance-check`、`taste-review`、合规门、排版门 |

`look.*`、`audio.*`、`style.*` 只产生候选，写入仍经 `edit.propose` 与 `edit.commit`。

### 3. 多风格方案 19 个新原子的归属

| 新原子 | 归属 | 模型怎样用到 |
| --- | --- | --- |
| `content-signal-extract`、`subject-safe-zone-detect`、`material-profile-build`、`shot-boundary-detect`、`beat-detect` | F 类，分析单元 | `media.profile`、`transcript.signals` |
| `style-route`、`design-token-resolve`、`style-pack-compile` | F 类，风格编译 | `style.route`、`style.plan` |
| `mg-component-render`、`caption-animate`、`sound-event-place`、`layer-compose` | F 类，渲染与声音单元 | 由编译器调度，模型不直接调用 |
| `style-conformance-check` | G 类，程序检查 | `review.check` |
| `taste-review` | G 类，模型评审（只出观察） | `review.prescreen`，在独立上下文中运行 |
| `multi-style-preview` | F 类 | `style.preview` |
| `style-memory` | L8 记忆服务 | `style.route` 读取；采用后写入 |
| `subject-matte`、`object-track`、`style-transfer-window` | F 类，机制单元（阶段 3） | 由机制包编译调度 |

全部 19 个在 `registry/skills.json` 中登记为 `visibility: internal`，不进入路由文档。

### 4. 兼容

`run_operation` 保留，供已有脚本与高级用户使用，在 `describe` 中标注“直接请求，调用方自行保证哈希与版本”。入口 Skill 的推荐路径改为工具组。`list_skills` 返回时区分 `internal` 与模型可见条目。

上线分三步（已定）：

| 步骤 | 做什么 | 条件 |
| --- | --- | --- |
| 1 并存 | 新工具组与 `run_operation` 同时提供；入口 Skill 推荐工具组 | 阶段 1 开始 |
| 2 按 E2 定去留 | 组合入口达标：`run_operation` 从入口 Skill 的说明中移除，MCP 中保留并标“直接请求”。不达标：保留原子直调，但哈希与版本仍由运行时持有 | E2 报告完成 |
| 3 ID 不变 | 现有原子 ID 一律不改名，作为内部单元与 `describe` 的下钻目标；脚本与回执中的旧 ID 继续有效 | 始终 |

## 五、知识层的体积预算

| 内容 | 现状 | v2 目标 |
| --- | --- | --- |
| 入口硬规则 | 入口 Skill + `router.md` 全文 + `skills.json`，约 2.2 万 token（估算） | 1,500–3,000 token |
| 场景卡 | 工作流连同参考 15.7–70.5 KB，影视解说 190 KB | 场景卡正文控制在 6–10 KB，参考按需读取 |
| 方法卡 | 580 张风格卡与方法卡混放 | 方法卡单独建索引，只读命中部分 |
| 风格数据 | 在路由文档中描述 | 不进上下文，由 `style.route` 读 |

`router.md` 不删除：其中的相邻歧义说明拆成方法卡和场景卡里的“退出条件”，供检索命中；入口只留硬规则。拆分后的效果由 [05](05-metrics-experiments.md) 的 E3 检验。

## 六、状态阶梯

所有 B、C、D 类资产共用一套状态，替代现有的 `authored-unvalidated`、`experimental-content-unvalidated` 等写法。

| 状态 | 条件 | 能否进入路由池或货架 |
| --- | --- | --- |
| `draft` | 已写成，结构检查通过 | 否 |
| `compiled` | 风格类：编译器在合成样例上通过；场景、方法类：在合成任务上跑通 | 否 |
| `measured` | 有无配对或 Oracle/Auto/None 已跑，结果为正或不显著但无负迁移 | 场景卡与方法卡可进入路由池 |
| `limited-trial` | 风格类：过 G0–G3（按聚类口径）；场景类：在 3 个以上真实项目上用过 | 可上货架 |
| `validated` | 10 个以上真实项目；局部修改成功率不低于 95% | 默认推荐 |
| `retired` | 新模型裸做已持平，或出现负迁移 | 否，保留记录 |

`retired` 很重要。模型升级后，部分方法会变得多余，继续加载只会增加路由负担。每次升级模型都用同一批测试重跑一次。
