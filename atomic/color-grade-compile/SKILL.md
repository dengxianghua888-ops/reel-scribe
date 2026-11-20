---
name: color-grade-compile
description: 把调用者明确给出的调色参数（曝光档、白平衡线性增益、高光柔和滚降、ASC CDL、曲线、HSL八色相带、外部cube LUT及混合比例、整体强度）按BT.709或sRGB显示解释编译成3D cube，并在可精确表示时导出.cc与CLF；报告编译LUT相对解析链的CIEDE2000误差。不选择风格、不测量素材、不改媒体。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 参数化调色编译

调用 `operation: color-grade-compile`，字段见[调色编译合同](../../contracts/color-grade-contract.md)。需要 numpy，不需要 FFmpeg。产物是 `grade.cube`，以及按请求导出的 `grade.cc`、`grade.clf` 和回执 `color-grade.json`；实际套用到视频仍用 [color-lut-apply](../color-lut-apply/SKILL.md)。

操作按列出顺序作用于显示参考的 R'G'B' 代码值，`interpretation` 选 `bt709-sdr-display`（BT.1886 γ2.4）或 `srgb-sdr-display`（sRGB 分段曲线），cube 只套用到同一传递函数的素材：曝光与白平衡在该线性光中计算且不在 1 处裁切，`highlight_rolloff` 把超出部分平滑压回 1 以内（`max-rgb` 保持色相饱和度，`per-channel` 亮部去饱和），CDL 为 ASC v1.2 带钳位语义，曲线在代码值上做单调三次（PCHIP）插值、总曲线先于各通道，HSL 按 RGB 色相环划分红/橙/黄/绿/青/蓝/紫/洋红八段、在 CIELAB 中旋转色相、缩放色度、平移 L* 并对低色度像素渐入保护，外部 LUT 以已验证字节解析并可按 mix 混合；每步钳位到 0–1，strength 在代码值上混合输入与整链输出。参数越界、未知字段、未知操作直接拒绝，不自动修正。

`.cc` 只在“恰好一个 CDL 且 strength=1”时导出，并在回执写明钳位语义差异；不使用钳位的宿主在超出 0–1 的区域会不同。CLF 在可精确表示时为参数化链，否则为编译 cube 的烘焙 LUT3D 并标明 mode。回执中的 CIEDE2000 自检比较的是本库参考插值与解析链，FFmpeg 或其他宿主的插值实现另行验证。

HSL 色相带是色相区域，不是肤色、天空或物体检测；编辑超出色域时逐通道裁切，裁切通道附近 γ2.4 暗部斜率很陡，含 HSL 时用 65 阶并读回执误差。曝光后若不接 `highlight_rolloff`，链末钳位仍是硬裁切；CDL 也按 ASC 语义钳位。提亮时在曝光后接滚降，或改用带肩部的曲线，并用 color-profile-scan 对比套用前后的高光裁切比例（真实照片实测见[色彩层真实素材操作记录](../../docs/color-real-run-20261119.md)）。

参数从哪里来（风格卡模板、参考测量、用户口头反馈）是上层的选择与证据；编译成功不代表画面更好看。比较 look 时保持同一素材、时间和其他变量不变，先用 [color-profile-scan](../color-profile-scan/SKILL.md) 测量，再由人看片判断。
