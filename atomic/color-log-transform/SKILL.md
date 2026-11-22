---
name: color-log-transform
description: 把调用者声明的相机Log视频（Apple Log、S-Log3、V-Log、LogC等）经带版本号的OpenColorIO内置配置或按哈希绑定的.ocioz归档按调用方选择的显示与视图，或经调用方提供的厂商Log转显示.cube，转换为BT.709或sRGB SDR，保留帧数与音轨，报告LUT烘焙误差、读回误差和超出码值或显示范围的比例；不猜测相机、码值范围或观感。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 相机 Log 输入的显式转换

Log 素材直接按 BT.709 解码会发灰、偏平，本库的色彩测量和作品调色也只接受 SDR。调用 `operation: color-log-transform` 先显式转换，字段见[相机 Log 输入转换合同](../../contracts/color-log-transform-contract.md)。命令从库根运行：`python3 runtime/editing_runtime.py run --request /absolute/request.json --work-dir /absolute/new-run`。需要 FFmpeg 的 zscale、lut3d 滤镜和 numpy；OCIO 模式另需 `opencolorio` Python 包，厂商 LUT 模式不需要。

- 声明三件事：Log 色彩空间（例如 `Apple Log`、`S-Log3 S-Gamut3.Cine`）、YUV 矩阵、码值按全范围还是视频范围解释。相机 Log 没有标准标签，这些只能由上层根据拍摄设置和厂商资料确定；文件的标签不一定可靠，例如 ARRI 的 ProRes Log C 被标成 BT.709 且没有范围标签，按厂商资料应声明视频范围。
- 转换二选一：`ocio` 写带版本号的内置配置名，或用 `{path, sha256}` 指向 `.ocioz` 归档（普通 `.ocio` 文件会引用哈希之外的 LUT，拒绝），视图由上层选，例如 ACES 2.0 的 SDR 视图有色调映射，`Un-tone-mapped` 没有；`lut` 给出厂商 Log 转显示的 3D `.cube` 及其输出显示，LUT 是否对应所声明的 Log 和显示只能由厂商文档保证。显示只有 Rec.709（BT.1886）和 sRGB 两种。
- 先用一两个采样帧试转，看回执：码值超出 [0,1] 的比例偏高，多半是码值范围声明反了；OCIO 模式下超出显示范围的比例偏高，说明所选视图会裁掉高光。
- 输出带 BT.709 或 sRGB 的 SDR 标签，帧数不变，音轨原样复制；之后按结果里的 `output_interpretation` 进入 color-profile-scan、作品调色或影视流水线。

不同视图或 LUT 画面不同，没有“正确”的一种；本原子只执行调用方的选择，不评价观感。相机写出的 Log 文件只验证过 ARRI AMIRA 的 ProRes Log C（用 ARRI 官方 LUT 时与相机自己的 Rec 709 输出一致），其他相机文件的标签与范围需要上层核对。
