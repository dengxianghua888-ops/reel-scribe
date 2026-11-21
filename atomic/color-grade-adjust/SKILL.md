---
name: color-grade-adjust
description: 把调用者按反馈映射表换算好的色温、色调、亮度、对比、饱和度累计步数（每维至多±3，可由风格卡收紧）转成固定步长的参数增量追加到调色层末尾，并在固定探针色上核对每一维的方向；不解析自然语言、不选风格、不采用。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 调色反馈的有界调整

看过预览的人说“暖一点”“对比强一些”时，先按[调色反馈合同](../../contracts/color-grade-adjust-contract.md)的映射表，把说法换算成五个维度（warmth、tint、exposure、contrast、saturation）的**累计**步数，再调用 `operation: color-grade-adjust`。命令从库根运行：`python3 runtime/editing_runtime.py run --request /absolute/request.json --work-dir /absolute/new-run`。需要 numpy。

- 传入的是**未调整的基础调色层**和累计步数，不是在上一次结果上继续叠加：“再暖一点”就把 warmth 从 1 改成 2，基础调色层不变。这样撤销某一维只需把它改回 0。
- 每维默认至多 ±3 步；风格卡可以用 `caps` 收得更紧，超出直接拒绝，不截断。
- 结果在固定探针色上核对每一维的方向（例如暖必须让中灰 b* 变大），方向不符直接失败；报告各探针的 ΔL*、Δa*、Δb*、Δ色度与 ΔE2000。
- 说法含糊（“高级一点”“有电影感”）不在映射表内，先问清楚具体想改哪一维，不要猜成步数。

输出的调色层是候选，仍需 color-grade-compile、预览，作品中还要经过保护项门禁。步长是固定参数增量，不是感知单位，不同素材的观感变化不同。
