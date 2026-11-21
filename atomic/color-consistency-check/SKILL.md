---
name: color-consistency-check
description: 比较同一时间线调色前后的视频：按调用者声明的色相范围或区域测量保护项的CIEDE2000偏差，并报告逐段闪烁、剪切、合法范围与相邻段漂移，只在声明了阈值或保护项时形成门禁；不评价好看、不识别肤色或人脸、不把颜色推向目标。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 调色一致性与保护项检查

调用 `operation: color-consistency-check`，字段见[调色一致性合同](../../contracts/color-consistency-contract.md)。命令从库根运行：`python3 runtime/editing_runtime.py run --request /absolute/request.json --work-dir /absolute/new-run`。需要 numpy；缺失时明确 `DEPENDENCY_UNAVAILABLE`。

提供调色前的 `reference` 与调色后的 `candidate`（同一时间线，帧数、尺寸一致）、`input_color`、按输出帧号划分的 `segments`（通常一段一个镜头）和 `samples_per_segment`。可选：

- `protections`：调用者声明要保持的颜色，`hue-range`（CIELAB 色相范围加最小色度）或 `region`（归一化矩形），各带中位 ΔE2000 上限和 `fail`/`flag` 动作；
- `limits`：闪烁增量、剪切增量、相邻段漂移增量、有限范围外亮度比例的上限。

输出 `color-consistency.json`，`gate` 为 `PASSED`、`FLAGGED` 或 `FAILED`。没有声明保护项和上限时只报告数值，门禁总是 `PASSED`。保护项只比较同一像素调色前后的变化：它“保持”颜色，不把肤色或品牌色推向任何标准值，也不检测人脸或肤色；色相范围选中的是符合色相和色度条件的像素，不一定是皮肤。只覆盖采样帧。

作品渲染（`work-render`）在调色步骤之后自动调用本原子，见[作品调色合同](../../contracts/work-color-contract.md)。
