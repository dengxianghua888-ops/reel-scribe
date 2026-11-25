---
name: color-lut-apply
description: 对已声明BT.709或sRGB SDR色彩解释和零起点恒定帧率视频应用指定3D cube LUT，保留帧顺序和音轨；不选择风格、不自动匹配参考色调、不做HDR或Log转换。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 显式 LUT 应用

调用 `operation: color-lut-apply`，提供source和lut文件的绝对path/sha256，input_color={space:bt709-sdr或srgb-sdr,range:limited或full,basis:verified-metadata或caller-declared}（srgb-sdr要求并保留iec61966-2-1传递函数标签；LUT作用于代码值，须以同一解释编译，sRGB素材用color-grade-compile的srgb-sdr-display），interpolation=tetrahedral或trilinear，可选strength（0<s≤1）在同一网格派生 identity+s×(lut−identity) 并记录派生cube哈希。也可用 layers 代替 lut：按列出顺序叠加多层 LUT，每层带明确的 [起始帧, 结束帧) 区间列表和可选 strength，区间外的帧保持源值，层间保持 32 位浮点 RGB；每个区间的中间帧和一帧区间外的帧会读回：在全分辨率上用请求的插值方式对源的每个像素做 numpy 预测（非线性 LUT 不能先平均再预测），再把预测与输出按至少 8×8 的块取平均后比较，这样输出编码抹掉的传感器噪声不算作误差（ΔE2000 中位数不超过 3，否则失败）。作品调色即由此实现。参数化调色先用[color-grade-compile](../color-grade-compile/SKILL.md)编译。入口见[运行器](../../runtime/editing_runtime.py)，实现见[color_ops.py](../../runtime/color_ops.py)。

原子只执行已选变换。复杂层先确认素材颜色解释、选择或制作LUT、试看代表帧、判断肤色和高光。元数据缺失时显式caller-declared，不冒充已验证；已知冲突拒绝。HDR/Log、旋转元数据、非零起点/VFR暂不支持，不隐式转换。支持8bit YUV420/422/444及全范围变体（输出8bit有限范围BT.709 H264 yuv420p），以及10bit YUV420/422/444（在gbrp10上套用LUT，输出10bit yuv420p10le，中途没有8bit环节）；结果的bit_depth记录源位深、LUT工作格式与输出位深。

cube只接受2–65阶3D表，域0–1，有限0–1值，精确N³行；红轴最快、绿次之、蓝最慢，轴语义由调用者负责。路径复制到固定selected.cube避免滤镜路径解释；未知字段、重复/晚出头部、缺行、多行拒绝。

输出graded.mp4和color-lut-map.json。检查每帧时间与源对应、帧数/几何不变；有音频时逐轨校验流数量、编码/采样率/声道及压缩载荷哈希，不支持的容器编码明确失败。输出色彩同时记录requested标签与observed探测值，未探测到的字段保持未知，不以写入参数冒充验证。此为有损重编码，不承诺像素无损或音量感知不变。

派生素材要在作品notes中保留原source→LUT→derived的回执引用。将原源区间映射到派生时间线，不能把派生哈希当原媒体身份；改变LUT生成新文件/回执并使相关渲染与QC失效。禁止重复烧录同一LUT，不能先调中间片再在最终片误调第二次。

源媒体在渲染前和成功回执发布前重新核对 SHA-256。发现源字节变更则失败，不发布调色映射或成功 result；失败目录留下的媒体只供诊断。该检查不是不可变快照，不能保证发现两次检查间被替换又恢复的输入。对可能被并发改写的输入，调用方应提供独立、稳定的源副本。
