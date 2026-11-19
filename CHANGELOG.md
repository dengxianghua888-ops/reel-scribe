# Changelog

## Unreleased

组件版本（含义见[构建与验证](docs/packaging.md#版本号的含义)）：runtime `0.17.0-dev`、MCP/插件 `0.1.0`、影视包 `0.3.0`。

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
  - 新增色彩层真实素材操作记录（docs/color-real-run-20261119.md）。
  - 色彩测试素材改用 `setparams` 在帧上写色彩标签；CI 上的 FFmpeg 没有写入输出端 `-color_trc`/`-color_primaries` 设置的标签，导致测试失败。
- 兼容性说明：
  - `chat_json` 请求改用 `:schema-json` 意图键，已有工作区重算模型阶段时不会重放旧结果，需要重新 `--allow-remote`；旧键下 UNKNOWN 的发送在核对前会阻止替代请求。
  - 已启用但不存在的故事上下文文件现在直接报错。
  - MCP 对未知协议版本回退到最新支持的 `2025-06-18`。

## v0.3.0-alpha.1 · 2026-09-28

- 将通用剪辑 Skill 库设为仓库顶层，纳入 34 个原子 Skill、16 条复杂工作流及可选 Agent 适配入口。
- 原 v0.2.0 影视解说项目并入 `workflows/raven-film-recap/douyin-film-recap/`；保留运行时代码、测试、Schema、安装器与 MIT 许可。
- 提供可选本地执行器与 MCP 桥接，以及共同来源时钟、音频处理、局部候选／采用／版本检查等当前源码改进。
- 新增面向用户的 README、接入与迁移说明、开发边界和宣传文案。
- 这是源码预览；不是全场景、真人用户链、编辑器兼容或全库效果验收。

旧版详细变化见[影视解说 Changelog](workflows/raven-film-recap/douyin-film-recap/CHANGELOG.md)。原 `v0.2.0` 标签和发行包保持不变。
