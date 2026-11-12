---
name: caption-burn
description: 按明确输出时间、字体文件、字号、颜色和边距烧录给定字幕；不改文案、不选择关键词、不自动设计字幕风格。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 明确样式字幕烧录

按 [原子合同](../../contracts/operation-contract.md) 请求 `caption-burn`。source/font 使用真实路径与哈希；传 font_family、font_size、margin_v、color_rgb 和 cues。字号和边距按实际视频画布像素定义，颜色为六位 RGB；字幕默认底部居中、黑色 1px 描边，当前不支持其他样式参数。

cue 包含 start/end/text，可选非空 `style_override` 只覆盖该条的 font_size、color_rgb、margin_v；未列字段继承全局，不能覆盖字体或传 ASS 指令。使用成片时间且按时间有序、不重叠。换行可用真实换行符；为了不让字幕正文注入 ASS 指令，含花括号、反斜杠或回车的正文暂时拒绝，不静默改字。复杂文字排版待显式扩展合同。

输出 captions.ass 与 captioned.mp4，保留原音轨。字体被提供不等于没有 fallback；必须检查实际中文字形、字幕完整性与安全区。技术成功仍不声称已通过视觉验收。

执行器：[editing_runtime.py](../../runtime/editing_runtime.py)。
