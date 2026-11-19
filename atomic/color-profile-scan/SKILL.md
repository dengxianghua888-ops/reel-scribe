---
name: color-profile-scan
description: 在明确源区间按显式采样测量已声明BT.709 SDR视频的色彩特征（影调分位数、剪切、CIELAB、色度、中性偏移、色相分布、调色板、样本间漂移、调用者声明区域的矢量示波角）；只返回数值，不评价好看、不识别肤色、不推荐风格。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 色彩特征测量

调用 `operation: color-profile-scan`，字段见[色彩特征合同](../../contracts/color-profile-contract.md)。命令从库根运行：`python3 runtime/editing_runtime.py run --request /absolute/request.json --work-dir /absolute/new-run`。需要 numpy；缺失时明确 `DEPENDENCY_UNAVAILABLE`。

提供 source 的绝对 path/sha256、start/end、采样方式（固定间隔或明确时刻）、max_samples、analysis_size、palette_colors 和 input_color={space:bt709-sdr, range:limited或full, basis:verified-metadata或caller-declared}。采样数超过上限直接拒绝，不静默抽稀。HLG、PQ、BT.2020/P3 广色域和与声明冲突的标签拒绝，不按 SDR 硬算；元数据缺失时只能 caller-declared，并在结果中列出未观测标签。

输出 `color-profile.json`：逐样本与汇总统计、调色板、样本间均值漂移、可选的调用者声明矩形区域。解释链（BT.709 解码、BT.1886 γ2.4、D65 CIELAB）写在结果里；原始解码帧读取后删除，只保留每帧 rgb24 哈希。

这些数字是参考风格迁移矩阵中的“参考证据”和“验收证据”候选：可以说明“参考片暗部更抬、色度更低、暖偏”，不能说明某个 look 更好看，也不能代表未采样帧。肤色线偏移只对调用者声明的区域计算，是参照而非目标；没有人脸或肤色检测。比较两条素材时使用相同 analysis_size、采样密度与区间语义，否则数值不可直接对比。
