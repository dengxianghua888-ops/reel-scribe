---
name: audio-mix
description: 将指定音频区间按明确时间位置和增益混入已有视频，保留原视频流；用于已确定的配音或配乐摆放，不选择音乐、不改写旁白、不自动裁短语音。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 明确声轨的摆放与混合

按 [原子合同](../../contracts/operation-contract.md) 请求 `audio-mix`。视频 source、base_gain_db 和 tracks 均必填；每轨包含 source/start/end/output_start/gain_db。所有 source 必须带真实哈希。

按 48kHz 音频采样点量化摆放时间；音频超过画面即返回 AUDIO_EXCEEDS_PICTURE，不剪短语音、不自动加速。原画面流复制，不替换剪点或构图。没有原声的视频显式建立静音底轨。

输出 mixed.mp4。混音不自动压低对白、不自动限幅或选择响度；声音所有权、重叠和音量由复杂 Skill 明确决定。当前技术验证不代表无削波、响度合适或听感通过，应对真实成片听检。

如需只在指定旁白窗口降低原声，提供可选 `base_gain_windows: [{start,end,gain_db}]`，gain_db 为该窗口绝对目标增益。窗口必须有序且不重叠；执行精度为 FFmpeg 音频帧边界，当前不提供平滑包络。不得以整片压低原声替代局部声部让位。

执行器：[editing_runtime.py](../../runtime/editing_runtime.py)。TTS 生成本身不在此操作内。

独立音轨可显式提供 `envelope: {sample_rate:48000, fade_in_samples:整数, fade_out_samples:整数, curve:"tri"|"qsin"}`，在源窗首尾执行淡变。入出点与输出位置须精确落在48kHz采样点；两段淡变之和不得超过源窗。省略字段保留旧混音路径。实现验证完整解码样本数，不补静音伪造覆盖；这不是自动配乐、自动对白避让或听感验收。Work绑定、保护与局部撤销限制见[作品合同](../../contracts/work-contract.md)。原声 `base_gain_windows` 仍为帧边界阶跃，不因新增独立轨淡变成为平滑原声包络。
