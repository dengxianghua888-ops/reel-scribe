---
name: color-grade-compile
description: 把调用者明确给出的调色参数（曝光档、白平衡线性增益、ASC CDL、外部cube LUT及混合比例、整体强度）编译成3D cube，并在可精确表示时导出.cc与CLF；报告编译LUT相对解析链的CIEDE2000误差。不选择风格、不测量素材、不改媒体。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 参数化调色编译

调用 `operation: color-grade-compile`，字段见[调色编译合同](../../contracts/color-grade-contract.md)。需要 numpy，不需要 FFmpeg。产物是 `grade.cube`，以及按请求导出的 `grade.cc`、`grade.clf` 和回执 `color-grade.json`；实际套用到视频仍用 [color-lut-apply](../color-lut-apply/SKILL.md)。

操作按列出顺序作用于显示参考的 BT.709 R'G'B'（0–1）：曝光与白平衡在 BT.1886 γ2.4 线性光中计算，CDL 为 ASC v1.2 带钳位语义，外部 LUT 以已验证字节解析并可按 mix 混合；每步钳位到 0–1，strength 在代码值上混合输入与整链输出。参数越界、未知字段、未知操作直接拒绝，不自动修正。

`.cc` 只在“恰好一个 CDL 且 strength=1”时导出，并在回执写明钳位语义差异；不使用钳位的宿主在超出 0–1 的区域会不同。CLF 在可精确表示时为参数化链，否则为编译 cube 的烘焙 LUT3D 并标明 mode。回执中的 CIEDE2000 自检比较的是本库参考插值与解析链，FFmpeg 或其他宿主的插值实现另行验证。

参数从哪里来（风格卡模板、参考测量、用户口头反馈）是上层的选择与证据；编译成功不代表画面更好看。比较 look 时保持同一素材、时间和其他变量不变，先用 [color-profile-scan](../color-profile-scan/SKILL.md) 测量，再由人看片判断。
