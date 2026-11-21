---
name: color-input-transform
description: 把调用者声明的HLG或PQ（BT.2020）视频按显式选择的色调映射算子与峰值转换为带BT.709 SDR标签的视频，保留帧数与音轨，并报告采样帧的实测峰值亮度、超出SDR参考白与BT.709色域的比例；不猜测素材类型、不自动选算子、不评价观感。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# HDR 输入的显式转换

手机 HLG、PQ 等 BT.2020 HDR 素材不能直接当 SDR 用：直接按 BT.709 解码会偏暗、发灰，本库的色彩测量、作品调色和影视流水线都会拒绝它们。调用 `operation: color-input-transform` 先显式转换，字段见[HDR 输入转换合同](../../contracts/color-input-transform-contract.md)。命令从库根运行：`python3 runtime/editing_runtime.py run --request /absolute/request.json --work-dir /absolute/new-run`。需要 FFmpeg 的 zscale 与 tonemap 滤镜，以及 numpy。

- 声明输入是 `hlg` 还是 `pq`；`verified-metadata` 要求标签齐全一致，`caller-declared` 允许缺失但拒绝冲突。
- 色调映射算子必须显式选择；除 `clip` 外还必须给出 `peak_nits`。可以先用 `clip` 或一组采样帧试转，读回执里实测的峰值亮度，再决定算子和峰值。
- 回执报告采样帧的实测峰值、超出 SDR 参考白和 BT.709 色域的比例；峰值与实测相差两倍以上时给出提示。
- 输出带 BT.709 SDR 标签，帧数不变，音轨原样复制；之后按 `bt709-sdr`、`verified-metadata` 进入 color-profile-scan、作品调色或影视流水线。

不同算子画面不同，没有“正确”的一种；本原子只执行调用方的选择，不评价观感。杜比视界只读取基础层。
