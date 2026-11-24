# Changelog

## Unreleased

组件版本（含义见[构建与验证](docs/packaging.md#版本号的含义)）：runtime `0.17.0-dev`、MCP/插件 `0.1.0`、影视包 `0.3.0`。

- 首页改版：中文首页重写，新增[英文首页](README.en.md)、20 秒演示（动图与高清 MP4）、“说一句话 Agent 就干活”示意图，以及一句话调色、胶片质感、相机 Log、统一影调和中文字幕的前后对比。演示画面由本库原子操作在 Netflix《Sparks》（CC BY 4.0）上生成，[署名与改动说明](provenance/distribution-notices/readme-demo-media-NOTICE.md)。另新增 Issue 模板和社交预览图，Codex 插件说明同步更新。
- 修复 `film-texture-apply` 遇到 2024:2025 这类像素宽高比时把输出写成 1:1、继而拒绝自己的输出：`setsar` 默认把比值约简到 100 以内的分子分母。
- 新增实验性[剧情创作与制作交接](workflows/raven-drama-production/SKILL.md)工作流，复杂工作流增至 17 条。
- 影视解说子集新增 OTIO 受限导出与回读、局部旁白修订、受保护修订与 `render-current`、可选增量渲染缓存、只读 HTML 证据报告，以及离线对齐导入与固定本地 CTC 执行。
- 运行时与 MCP 新增协作取消与进度，并在请求封装、生成任务与文本 Provider 账本、Work／批量／候选字节绑定上持续收紧为失败即关闭。
- 2026-11-17 全仓审查（[记录](docs/20261117-repository-review.md)）：
  - 未归类缺陷也写 FAILED receipt；
  - 绑定已验证的 JSON 控制文件、故事上下文和静帧字节；
  - 修复含 `'`、`\` 路径的字幕烧录；
  - Schema 提示改为 JSON；
  - 影视配置支持 `30000/1001` 等有理帧率；
  - 单次运行内复用相同的解码时钟观察；
  - CI 增加未使用名称检查，并用 `concurrency` 取消同一分支上被新推送取代的运行。
- 色彩层 C0（[规划](docs/color-layer-plan-20261119.md)）：
  - 新增原子 `color-profile-scan`：显式采样，测量影调、剪切、CIELAB、色度、色相分布、调色板、样本漂移和声明区域的矢量示波角；只给数字，不评价好看。
  - `install_doctor` 记录色彩滤镜与 HDR 转换路线的可用性。
  - 新增合成色彩测试素材生成器（tests/runtime/color_media.py）。
  - 影视解说拒绝 HLG/PQ/BT.2020 源（`SOURCE_HDR_INPUT_UNSUPPORTED`）。原先会静默输出偏暗、发灰的 8 位视频。
- 色彩层 C1：
  - 新增原子 `color-grade-compile`，把曝光、白平衡增益、ASC CDL、外部 LUT（含 mix）和整体强度编译为 cube，按可表示性导出 `.cc` 和 CLF，并报告 CIEDE2000 编译误差。
  - `color-lut-apply` 新增可选 `strength`，并改为解析与套用同一份已验证的 LUT 字节。
  - 共享数值模块 `color_numerics`。
  - `color-profile-scan` 合并统计改为按样本流式累加，峰值内存与样本数无关（原实现在 600 帧 × 512² 上限下需数 GB）。
  - `color-grade-compile` 新增曲线（PCHIP，总曲线先于通道）和 HSL 八色相带（在 CIELAB 中调整，带低色度保护）；含这两种操作时 CLF 导出烘焙 LUT3D。
  - `color-lut-apply` 支持 10 位源，全程 10 位处理和输出；结果新增 `bit_depth`，`video` 新增 `pix_fmt`。
  - `still-image-render` 的色彩标签同时写在帧上，不再只依赖输出端选项。
  - 新增色彩层真实素材操作记录（docs/color-real-run-20261119.md），含两轮真实照片操作。
  - 色彩原子接受 sRGB：`color-profile-scan`/`color-lut-apply` 新增 `space: srgb-sdr`，`color-grade-compile` 新增 `interpretation: srgb-sdr-display`，sRGB 的 CLF 用 `monCurve` 精确表示。
  - 色彩层 C2a：WorkDocument 新增可选 `color` 段（`work-color/1`：输入解释、调色层、目标片段、顺序），修订范围新增 `grade_ids`、`color_inputs`，调色层覆盖的源内容变化须复核；`work-render` 在时间线之后、混音/叠层/字幕之前按片段帧区间调色；`color-lut-apply` 新增 `layers` 模式（多层 LUT 按帧区间叠加、32 位浮点、逐区间读回）。
  - 色彩层 C2b：`prepare-local-undo` 支持单独撤销某个调色层的一个字段；`style-recipe-compile` 新增 `color_grade` 参数组（能力 `color-grade`），`style-recipe-preview` 因此可做调色 A/B 预览；`revision-impact-inspect` 新增 `color-grade` 阶段，调色变化只要求重做调色和渲染。
  - C2a 评审修复：分层套用的读回预测不再重复叠加层强度（原先按 s² 预测，正确输出会被判失败）；读回改为逐点取样，不再先平均再套 LUT；调色层覆盖内容按片段 ID 比较，互换片段顺序不再误报需要复核；读回按请求的插值方式预测（原先固定用四面体）。
  - 色彩层 C2c：新原子 `color-consistency-check` 比较同一时间线调色前后的画面，按调用者声明的保护项（色相范围可限定区域，或纯区域）和上限（闪烁、剪切、漂移、有限范围外亮度）形成门禁；作品 `color` 段新增 `protections`、`limits` 与范围键 `color_checks`，`work-render` 在调色之后运行检查，`FAILED` 时中止。
  - 色彩层 C3a：新原子 `color-reference-fit`，按 reinhard-lab、mvgd（MKL）或逐通道直方图把目标帧的色彩统计向参考迁移，拟合为可编辑的 ASC CDL 或逐通道曲线调色层草案，报告迁移前、理想迁移与拟合后的分布距离和拟合残差；不采用、不选强度、不声称像参考。评审修复：直方图曲线合并并列码值后再插值（原先量化素材会偏向分位数区间的一端）；JS 直方图的 a*/b* 范围扩到 ±128，覆盖 BT.709 纯蓝（b* 约 −108）。
  - 色彩层 C3b：新原子 `color-grade-adjust`，把按映射表换算好的色温、色调、亮度、对比、饱和度累计步数转成固定步长、有上限的参数增量，追加到调色层末尾，并在探针色上逐维核对方向；映射表写在调色反馈合同中。
  - 色彩层 C3c：6 张色彩类风格卡新增参数模板（拟合方法、拟合区间、强度上限、反馈调整上限、建议保护项、禁用条件）；`color-reference-fit` 新增可选 `bounds`；参考风格工作流的色彩维度改为可执行链路。
  - 色彩层 C4a：新原子 `color-input-transform`，按调用者声明的 HLG/PQ 输入和显式选择的色调映射算子、峰值，转换为 BT.709 SDR，报告采样帧的实测峰值亮度、超白和色域外比例；作品调色与色彩测量拒绝 HDR 时的错误提示改为指向它。
  - 色彩层 C4b：新原子 `film-texture-apply`，按显式参数依次施加光晕、暗角、颗粒（颗粒带种子可复现），保持帧数与音轨，逐效果读回实际贡献；YUV/RGB 转换使用精确取整，避免整体偏暗。只接受零起点恒定帧率、无旋转的输入，渲染与读回都只读第一条视频流，解码与编码进程受取消和 300 秒无进展监督，输出保留源的样本宽高比。
  - 色彩层 C4c：作品 `color` 段新增可选 `texture`（胶片质感参数），`work-render` 在调色门禁之后、混音、叠层和字幕之前对整个画面施加，读回帧取至多 4 个片段的中间帧；所有片段须声明同一种色彩解释。新增范围键 `color_texture`，影响分析新增阶段 `film-texture` 与分类 `color-texture`，带质感时重新调色也会重做质感。时间线没有传递函数标签时，若所有片段声明了同一种解释，调色步骤按该解释套用并写入对应标签（此前一律按 BT.709）。
  - 色彩层 C4d：新原子 `color-log-transform`，按调用者声明的相机 Log 色彩空间、码值范围和 YUV 矩阵，经带版本号的 OpenColorIO 内置配置与显式选择的显示、视图转换为 BT.709 或 sRGB SDR，报告烘焙误差、读回误差和超出码值或显示范围的比例。依赖诊断新增 `opencolorio` 包，CI 安装 `opencolorio==2.6.0`。
  - `color-log-transform` 新增两种转换来源：按哈希绑定的 `.ocioz` 归档（配置与其 LUT 同在一个文件；普通 `.ocio` 文件仍拒绝），以及调用方提供的厂商 Log 转显示 3D `.cube`（不需要 OCIO，依赖诊断按模式去掉 `opencolorio`）。实现中发现 OCIO 在进程内按归档内路径缓存 LUT 文件，两个归档里同名而内容不同的 LUT 会共用先读到的数据；现在先把归档复制到私有目录并核对哈希，在锁内清空缓存后建立处理器。
  - `color-lut-apply` 分层模式（作品渲染调色）的读回改为在全分辨率逐像素预测、按块平均后比较，块边长至少 8，每帧最多预测 131072 个像素；回执的 `analysis_size` 换成 `block`、`block_stride`、`blocks_per_frame`。原先逐点比较时，一层恒等 LUT 在噪声 σ 为 8/255 的画面上就会超过门禁、中止作品渲染；ARRI 相机片段的读回由 1.32–1.40 降为 0.57–0.60。`color-log-transform` 的块边长同样至少为 8。两处的解码改用同一个带看门狗的逐帧流式读取。
  - `color-log-transform` 的读回改为在全分辨率逐像素预测后按块平均比较（1080p 为 8×8），回执新增 `readback.block`。ARRI 相机写出的 Log C 片段在逐点比较下因传感器噪声被误判失败（2.2–3.0），改后为 0.45–0.52；整体偏暗 15% 的渲染仍被拒绝。真实内容记录新增第三部分：ARRI AMIRA ProRes 4444 Log C 样片，以及用 ARRI 官方 LUT 与相机自己的 Rec 709 输出的对照。
  - 相机 Log 真实内容记录新增第二部分：《Sparks》真实拍摄的 ACES 场景数据编码成 Apple Log 与 S-Log3 后转换，并记录视频范围文件误声明为全范围时回执无法发现的情况。
  - Blender 剪切读回新增 `--grades-output`、`--interpretation`：显式要求时，画面条带上的单个 Color Balance 按调色桥的读取规则读成调色文件，记录宿主与包摘要，与 OTIO 一起发布；默认仍拒绝任何修饰器，其他修饰器照旧拒绝。
  - 色彩层 C4：实验工具 `tools/editor-adapters/blender_color_balance.py`，在剪切导入器生成的 Blender 工程（4.3、5.3 系列）中，把单个 ASC CDL 的调色层写成片段的 Color Balance 修改器，并把 Offset/Power/Slope 或 Lift/Gamma/Gain 修改器读回为 `cdl` 调色层；表达不了的调色层拒绝，不做近似。
  - 修复逐条字幕配方会顺带改写调色层：cue 模式下配方里的调色层必须与作品一致，否则 `CUE_RECIPE_GLOBAL_CHANGE_FORBIDDEN`。调色配方携带已绑定的逐条字幕覆盖时必须完整携带并保留排版约束；配方一次新增多个调色层时按 ID 顺序追加。
  - 修复 `visual-layer-render` 彩色叠层偏色：不透明度改为直接缩放 alpha，叠层全程保持 BT.709 YUVA，不再经过矩阵不一致的 RGB 往返。
  - 新原子 `still-color-normalize`：按内嵌 ICC 用 LittleCMS 把静图转换为无配置文件的 sRGB PNG，可选应用 EXIF 方向；未标记图片只按调用者声明处理。
  - `color-grade-compile` 新增 `highlight_rolloff`（max-rgb / per-channel）。链模型调整为曝光与白平衡不在 1 处裁切，CDL、曲线、HSL、LUT 读入时各自钳位，整链输出末端钳位。由于该原子尚未发布，这次调整没有兼容影响。
  - 色彩测试素材改用 `setparams` 在帧上写色彩标签；CI 上的 FFmpeg 没有写入输出端 `-color_trc`/`-color_primaries` 设置的标签，导致测试失败。
- 兼容性说明：
  - `chat_json` 请求改用 `:schema-json` 意图键，已有工作区重算模型阶段时不会重放旧结果，需要重新 `--allow-remote`；旧键下 UNKNOWN 的发送在核对前会阻止替代请求。
  - 已启用但不存在的故事上下文文件现在直接报错。
  - MCP 对未知协议版本回退到最新支持的 `2025-06-18`。
  - `revision-impact-inspect` 的阶段列表在 `timeline` 与 `caption-layout` 之间新增 `color-grade`，按位置读取阶段的调用方需要调整。
  - `visual-layer-render` 彩色叠层的输出像素会改变（改为正确颜色）。

## v0.3.0-alpha.1 · 2026-09-28

- 将通用剪辑 Skill 库设为仓库顶层，纳入 34 个原子 Skill、16 条复杂工作流及可选 Agent 适配入口。
- 原 v0.2.0 影视解说项目并入 `workflows/raven-film-recap/douyin-film-recap/`；保留运行时代码、测试、Schema、安装器与 MIT 许可。
- 提供可选本地执行器与 MCP 桥接，以及共同来源时钟、音频处理、局部候选／采用／版本检查等当前源码改进。
- 新增面向用户的 README、接入与迁移说明、开发边界和宣传文案。
- 这是源码预览；不是全场景、真人用户链、编辑器兼容或全库效果验收。

旧版详细变化见[影视解说 Changelog](workflows/raven-film-recap/douyin-film-recap/CHANGELOG.md)。原 `v0.2.0` 标签和发行包保持不变。
