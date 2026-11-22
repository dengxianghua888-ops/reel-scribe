---
name: color-log-transform
description: 把调用者声明的相机Log视频（Apple Log、S-Log3、V-Log、LogC等）经带版本号的OpenColorIO内置配置，按调用方选择的显示与视图转换为BT.709或sRGB SDR，保留帧数与音轨，报告LUT烘焙误差、读回误差和超出码值或显示范围的比例；不猜测相机、码值范围或观感。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 相机 Log 输入的显式转换

Log 素材直接按 BT.709 解码会发灰、偏平，本库的色彩测量和作品调色也只接受 SDR。调用 `operation: color-log-transform` 先显式转换，字段见[相机 Log 输入转换合同](../../contracts/color-log-transform-contract.md)。命令从库根运行：`python3 runtime/editing_runtime.py run --request /absolute/request.json --work-dir /absolute/new-run`。需要 FFmpeg 的 zscale、lut3d 滤镜，numpy，以及 `opencolorio` Python 包。

- 声明三件事：Log 色彩空间（例如 `Apple Log`、`S-Log3 S-Gamut3.Cine`）、YUV 矩阵、码值按全范围还是视频范围解释。相机 Log 没有标准标签，这些只能由上层根据拍摄设置和厂商资料确定；文件的范围标签不一定可靠。
- OCIO 配置必须写带版本号的内置配置名，显示只有 Rec.709（BT.1886）和 sRGB 两种；视图由上层选，例如 ACES 2.0 的 SDR 视图有色调映射，`Un-tone-mapped` 没有。
- 先用一两个采样帧试转，看回执：码值超出 [0,1] 的比例偏高，多半是码值范围声明反了；超出显示范围的比例偏高，说明所选视图会裁掉高光。
- 输出带 BT.709 或 sRGB 的 SDR 标签，帧数不变，音轨原样复制；之后按结果里的 `output_interpretation` 进入 color-profile-scan、作品调色或影视流水线。

不同视图画面不同，没有“正确”的一种；本原子只执行调用方的选择，不评价观感。目前只用 OCIO 合成的 Log 素材验证过，真实相机文件的标签与范围需要上层核对。
