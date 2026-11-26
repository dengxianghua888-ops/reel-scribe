# 05 原子能力与协议增量（剪辑侧）

原则：新原子与现有原子同一口径——宿主中立、显式输入、证据输出、不自动采用；需要判断的部分留在复杂层。优先级 P0 / P1 / P2 对应 [08 路线图](08-taste-eval-roadmap.md) 的三期。

## 一、新增原子总表

| ID | 层 | 输入 → 输出 | 确定性 | 优先级 | 与现有能力的关系 |
|---|---|---|---|---|---|
| `content-signal-extract` | 分析 | 绑定的逐词稿（＋可选参考稿）→ `SignalSet`：数值、规格对、列表、步骤、引语、比较、转折、问题、主张、例子、故事节拍、情绪峰、幽默、商品提及、章节边界、强调词，均带词 ID 区间 | 数值与单位用确定性规则；其余为模型观察，带置信度 | P0 | 消费 `transcript-import` 输出；不做删改决定 |
| `subject-safe-zone-detect` | 分析 | 视频 ＋ 采样间隔 → 每段人脸/主体框、空闲侧、可放图形区域 | 检测模型，输出框与置信度 | P0（先人脸）/ P1（主体） | 为 `style-recipe` 的 `layout_constraints` 自动提供保护区；不替代人工遮挡审查 |
| `material-profile-build` | 分析 | 上述信号 ＋ `media-inspect` ＋ `color-profile-scan` ＋ `media-signal-scan` ＋ 上下文 → `material-profile/1` 与派生指标 | 聚合为确定性 | P0 | 新增；只聚合不判断 |
| `shot-boundary-detect` | 分析 | 视频 → 切点与景别估计 | 确定性阈值＋可选模型 | P1 | 研究库已有 PySceneDetect 机制材料；用于 B-roll 盘点与节奏画像 |
| `beat-detect` | 分析 | 音乐 → 拍点、小节、段落能量 | 确定性 | P2 | 与 `cue-alignment-check` 配合；不把音量峰当重拍 |
| `style-route` | 风格 | 画像 ＋ StyleIntent ＋ 包注册表 ＋ 能力声明 ＋ 风格记忆 → `style-route-result/1` | 谓词与打分确定性；可复算 | P0 | 取代 `creation-recommendation` 的字号比较在风格层的角色；后者保留 |
| `design-token-resolve` | 风格 | 设计系统 ＋ 品牌覆写 ＋ 画幅 → 解析后的 tokens（颜色、字体文件哈希、版位矩形、运动参数） | 确定性 | P0 | 字体绑定沿用 `caption_font_binding` |
| `style-pack-compile` | 风格 | 风格包 ＋ 画像 ＋ 当前 Work ＋ WordPlan ＋ 范围 → `style-plan/1` ＋ `work-candidate/1` | 调度与版位求解确定性；方法执行由上层给入 | P0 | 是 `style-recipe-compile` 的上位；后者继续服务显式参数 |
| `mg-component-render` | 渲染 | 组件模板 ＋ 实例属性 ＋ tokens ＋ 时长 → 带 alpha 的图层视频或 PNG 序列 ＋ 渲染回执 | 确定性（模板引擎版本固定） | P1（P0 用静态降级） | 扩展 `visual-layer-render`；首选 HTML/CSS 模板经无头浏览器逐帧渲染，备选 ASS 与 FFmpeg 滤镜 |
| `caption-animate` | 渲染 | 字幕轨 ＋ 字幕刻面 ＋ 强调词 → 带动画的 ASS 或图层 | 确定性 | P1 | 扩展 `caption-burn`；逐词高亮、关键词变色、弹入、打字机 |
| `sound-event-place` | 声音 | 声音刻面 ＋ 触发事件 ＋ 节目音轨 → 音效与音乐床摆放 ＋ 避让包络 | 确定性 | P1 | 生成 `audio-mix` 与 `audio-envelope` 请求；不生成新声音 |
| `layer-compose` | 渲染 | 多图层 ＋ 关键帧变换 ＋ 混合模式 ＋ 遮罩 → 合成层 | 确定性 | P2 | 静态矩形叠层的扩展 |
| `style-conformance-check` | 检查 | 成片 ＋ StylePlan ＋ 包的检查项 → 逐项报告 | 确定性测量＋声明阈值 | P0 | 与 `color-consistency-check`、`caption-coverage-check` 并列 |
| `taste-review` | 检查 | 成片抽帧联系表 ＋ 样段 ＋ 包的签名与克制规则 → 按评分表的观察报告 | 模型观察，非权威 | P1 | 只出证据与疑点，不签“好看”；盲评另行记录 |
| `multi-style-preview` | 检查 | 同一素材 ＋ 2–4 个风格包 → T1 风格帧联系表与 T2 样段 ＋ 对照页 | 确定性 | P0 | 扩展 `style-recipe-preview`，从字幕参数对照升级到整包对照 |
| `style-memory` | 记忆 | 采用后的 Work 版本 ＋ 包与微调 ＋ 作用域（品牌/系列/个人） → 记忆条目；查询接口 | 确定性 | P1 | 只记录已采用版本；不把 `user-reported` 反馈当授权 |
| `subject-matte` | 机制 | 视频 → 主体遮罩序列 | 模型 | P2 | 杂志分层、文字穿插人物前后 |
| `object-track` | 机制 | 视频 ＋ 初始框 → 跟踪框序列 | 模型 | P2 | 线框标签跟随实物 |
| `style-transfer-window` | 机制 | B-roll 区间 ＋ 风格参考 → 转绘片段 | 模型或生成服务 | P2 | 真人转手绘窗口；需跨帧稳定检查 |

## 二、关键原子的规格要点

### `content-signal-extract`

- **输入**：`transcript-import` 绑定的逐词稿（文本、词 ID、源时间、修订号）；可选参考稿。
- **输出**：信号列表，每条含 `type`、`word_ids`、`source_range_ms`、`text`、结构化字段（如数值信号的 `value`、`unit`、`label`）、`source`（`rule` / `model`）、`confidence`、`model_identity`（模型时）。
- **边界**：信号是观察，不是删改决定；数值规则只认“数字＋单位”的显式模式，“十几个小时”这类模糊量标 `approximate`；同一数值在开头与正文各出现一次时分别成条，避免研究库提到的“只删开头”类歧义。
- **验收**：在 3 条真实中文测评上，人工标注数值与规格对的召回 ≥ 0.9、精确 ≥ 0.95；引语与转折单独统计，不合并成一个分数。

### `style-route`

- **输入**：`material-profile/1`、StyleIntent、包注册表快照（含每个包的摘要）、能力声明、风格记忆查询结果、路由参数（权重、阈值、K）。
- **输出**：`style-route-result/1`：每个包的资格结论与原因、各分项分数、风格向量、被选方向及角色（稳妥/特色/反差）、解释文本、证据引用、代价、两两相似度。
- **可复算**：重新读取同一输入必须得到同一结果；输入或包变更后旧结果失效（沿用 `creation-recommendation` 的重算核对做法）。
- **边界**：不读视频、不判断审美；Agent 推翻排序须写理由。

### `style-pack-compile`

- **输入**：风格包及其刻面摘要、画像、WordPlan（方法刻面已执行的结果）、当前 Work 与 `expected_document_sha256`、范围授权。
- **输出**：`style-plan/1`（全部事件、实例、版位、降级记录）、`work-candidate/1`、`revision-diff.json`。状态 `CANDIDATE_COMPILED`、`render: NOT_RUN`、`style_effect: NOT_VERIFIED`。
- **拒绝条件**：刻面摘要不符、范围不足、保护项冲突、必需能力缺失且包未声明降级。
- **验收**：同一 WordPlan ＋ 两个皮肤包编译出的 StylePlan，事件时间完全一致，只有 tokens 与模板不同；同一包重复编译字节相同。

### `mg-component-render`

- **模板引擎**：首选 HTML/CSS（可用设计 token 变量，中文排版能力强），以无头 Chromium 固定版本逐帧截图为带 alpha 的 PNG 序列再封装；备选 ASS（文字类）与 FFmpeg 滤镜（简单形状）。模板与引擎版本写入回执。
- **属性校验**：按组件属性表校验类型、范围、枚举、最大字数；拒绝未声明属性。
- **验收（研究库提出的局部修改例）**：同一规格表组件在一条片中出现两次；只把第二处“500 g”改为“0.5 kg”；第一处、模板默认、原声、其余字幕保持；冷开工程、导出后在第二处看到新值。

### `style-conformance-check`

包声明的检查项与测量方式：

| 检查 | 测量 | 默认阈值（可由包覆写） |
|---|---|---|
| `value-word-sync` | 组件出现时间与锚定数值词起点之差 | −300 ms ≤ Δ ≤ +200 ms |
| `face-occlusion` | 组件与人脸框交并比 | IoU = 0 |
| `density-budget` | 每分钟组件事件数、同屏组件数 | 不超过包声明 |
| `unit-integrity` | 组件显示的数值与单位与信号字段一致 | 完全一致 |
| `token-compliance` | 抽帧中强调色面积占比、字号不低于最小可读 | 不超过设计系统上限 |
| `caption-band` | 字幕带与组件区不相交 | 沿用 `layout_constraints` 覆盖检查 |
| `look-consistency` | 相邻镜头色彩漂移、肤色色相 | 沿用 `color-consistency-check` |

## 三、合同与模型的修改

| 对象 | 修改 | 兼容性 |
|---|---|---|
| [Work 合同](../../contracts/work-contract.md) | 新增 `components[]`：`instance_id`、`template {id, version, sha256}`、`overrides`、`anchor {word_ids, source_range_ms}`、`output_range`、`placement {slot, rect}`、`z`；`scope` 新增 `component_ids`；`style_bindings` 记录包 ID/版本/摘要、各刻面摘要、StylePlan 摘要 | 旧作品无 `components` 时行为不变 |
| [风格配方合同](../../contracts/style-recipe-contract.md) | 保持 `style-recipe/1` 只做显式参数；新增 `style-plan/1` 由 `style-pack-compile` 消费；两者都编译到同一 Work 候选 | 旧配方继续可用 |
| [修改影响合同](../../contracts/revision-impact-contract.md) | 识别组件实例、设计系统 token、字幕刻面的依赖；改设计系统时列出所有受影响实例 | 增量 |
| 局部撤销 | 组件覆盖值可单独撤回，规则同字幕单条覆盖 | 增量 |
| [证据合同](../../contracts/evidence-contract.md) | 声明绑定规则对保护项只读；组件显示的数值若来自保护词，须与保护项一致 | 增量 |
| [能力交接合同](../../contracts/capability-handoff.md) | 能力名新增 `component-instance-write`、`caption-animation`、`subject-detect`、`signal-extract` | 增量 |
| `registry/skills.json` | 新原子以 `status: planned` 登记，实现后改为实际状态 | 结构检查需同步 |
| [router.md](../../registry/router.md) | 新增“风格选择与多风格对照”一节（见 03 章 §十） | 文档 |
| 风格卡 `catalog.json` | 可选新字段：`fit_signals`、`anti_signals`、`requires_signals`、`vector`（7 轴）、`signature`；先补口播 21 张与商品 57 张 | 可选字段不影响 `verify_library.py` 现有必填检查 |
| `scripts/verify_library.py` | 新增包与刻面结构检查（见 04 章 §六） | 新增检查项 |

## 四、方法卡结构化示例

现有“证据解释”卡增加的可选字段（仅示意）：

```json
{
  "id": "evidence-led",
  "fit_signals": [
    {"signal": "derived.numeric_density_per_min", "op": ">=", "value": 1.0, "weight": 0.3},
    {"signal": "derived.argument_ratio", "op": ">=", "value": 0.3, "weight": 0.3},
    {"signal": "signals.comparison", "op": "count>=", "value": 2, "weight": 0.2}
  ],
  "anti_signals": [
    {"signal": "derived.story_ratio", "op": ">=", "value": 0.6, "weight": -0.4}
  ],
  "vector": {"tempo": 0.55, "density": 0.5, "ornament": 0.3, "warmth": 0.4, "contrast": 0.6, "formality": 0.7, "motion": 0.4},
  "signature": "每个结论后紧跟它的依据，图形只服务依据"
}
```

## 五、宿主等价实现

这些原子在 ChatCut、剪映或其他编辑器中可以由宿主工具替代，按能力交接合同核对：组件实例改值对应宿主的“按实例 ID 写已声明属性”；字幕动画对应宿主字幕样式；主体检测对应宿主跟踪构图。宿主不提供读回时，相应检查标 `not-verifiable`，不伪造通过。
