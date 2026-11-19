---
name: still-color-normalize
description: 把带内嵌ICC配置文件（如Adobe RGB、sRGB）或按调用者声明为sRGB的PNG/JPEG/WebP静图用LittleCMS显式转换为无配置文件的sRGB PNG，可按要求应用EXIF方向；不调色、不增强、不猜测未标记图片。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 静图色彩规范化

调用 `operation: still-color-normalize`。实现见 [still_color_ops.py](../../runtime/still_color_ops.py)，需要 Pillow（含 ImageCms，即 LittleCMS）和 numpy，不需要 FFmpeg。

| 字段 | 约束 |
|---|---|
| `source` | `{path, sha256}`；单帧 PNG、JPEG 或 WebP，模式为 RGB、RGBA、P、L、LA 或 CMYK，最多 1 亿像素。16 位与浮点图拒绝 |
| `target` | 只接受 `srgb` |
| `rendering_intent` | `relative-colorimetric` 或 `perceptual` |
| `black_point_compensation` | 布尔值 |
| `untagged` | `reject` 或 `assume-srgb`；无 ICC 时的处理方式由调用者明确给出 |
| `orientation` | `require-upright`：EXIF 方向不是 1 时拒绝；`apply`：按 EXIF 方向转正 |

**色彩依据，按顺序判断**：
1. 有内嵌 ICC：配置文件的数据色彩空间必须与像素模式一致（RGB/GRAY/CMYK），设备类别为显示器、扫描仪、打印机或色彩空间。用 LittleCMS 按指定意图转换到内置 sRGB。
2. 没有 ICC：
   - CMYK 拒绝（`STILL_NORMALIZE_CMYK_PROFILE_REQUIRED`）。
   - PNG 带 sRGB 块，按 sRGB 处理。
   - 只带 gAMA/cHRM 块时拒绝，本原子不解释这两种块。
   - 其余情况由 `untagged` 决定：`reject` 报 `STILL_NORMALIZE_UNTAGGED_REJECTED`；`assume-srgb` 原样复制码值，回执标为 `caller-declared-srgb`，表示这是调用者的声明，不是验证结果。

**输出**：
- `normalized.png`：RGB，或保留原 alpha 的 RGBA。不含 ICC 和 EXIF。
- `still-color-normalize.json`：记录以下内容：
  - 源格式、模式与尺寸；
  - ICC 描述、色彩空间、设备类别、版本和哈希；
  - LittleCMS 与 Pillow 版本、意图、黑点补偿；
  - EXIF 方向及是否应用；
  - RGB/灰度源的码值改变量（最大值、均值）；
  - 输出哈希。
- sRGB 配置文件的图片经转换后，码值改变量通常是 0 或 1。改变量大说明源确实不是 sRGB。

**下一步**：用 [still-image-render](../still-image-render/SKILL.md) 以 `input_color=srgb` 渲染。色彩原子以 `space=srgb-sdr` 测量或套用，调色编译用 `interpretation=srgb-sdr-display`。真实照片实测见[色彩层真实素材操作记录](../../docs/color-real-run-20261119.md)。

本原子不调色、不提亮、不修复色偏，也不判断照片应不应该用。出了色域的颜色按所选意图处理，不再做额外修饰。
