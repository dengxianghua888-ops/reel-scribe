---
name: color-reference-fit
description: 把目标帧按参考帧的色彩统计（CIELAB均值方差、多元高斯MKL或逐通道直方图）迁移，并拟合成可编辑的ASC CDL或逐通道曲线调色层草案，报告迁移前、理想迁移与拟合后的分布距离和拟合残差；不采用、不选强度、不声称像参考。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 参考色彩迁移拟合

调用 `operation: color-reference-fit`，字段见[参考色彩迁移合同](../../contracts/color-reference-fit-contract.md)。命令从库根运行：`python3 runtime/editing_runtime.py run --request /absolute/request.json --work-dir /absolute/new-run`。需要 numpy；缺失时明确 `DEPENDENCY_UNAVAILABLE`。

提供参考与目标各自的视频、`input_color`（BT.709 或 sRGB SDR）和明确帧号，选一种方法：

- `reinhard-lab`：CIELAB 各通道均值、标准差对齐，拟合为 ASC CDL；
- `mvgd`：RGB 多元高斯之间的 Monge–Kantorovich 线性映射（Pitié），拟合为 ASC CDL；
- `histogram`：逐通道直方图匹配，拟合为逐通道曲线。

输出 `color-reference-fit.json`：可直接交给 [color-grade-compile](../color-grade-compile/SKILL.md) 的调色层草案、迁移前/理想迁移/拟合后三组与参考的距离（平均色 ΔE2000、Lab 切片 Wasserstein、Lab 直方图 JS 散度）和拟合残差。草案 `adopted: false`，强度不选；是否采用、用多大强度、需要哪些保护项，由上层结合预览和 [color-consistency-check](../color-consistency-check/SKILL.md) 决定。

距离变小只说明采样帧的色彩分布更接近，不代表“像参考”或更好看：统计量不看内容和构图，不同场景统计相近也可能观感无关。参考图片先经 still-color-normalize 与 still-image-render 转成视频。
