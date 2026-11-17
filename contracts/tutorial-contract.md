# 软件教程操作合同 v1

所有 path 为绝对文件路径；source/evidence 使用 `{path,sha256}`，hash 为真实文件 SHA-256。操作统一通过 [原子执行器](../runtime/editing_runtime.py) `run --request ... --work-dir ...` 调用。

## screen-focus

请求字段：

```text
operation: screen-focus
source: {path, sha256}
crop: {x, y, width, height}              # 原源视频像素，均为偶数
output: {width, height}                 # 偶数尺寸，与 crop 宽高比相同
highlights: [{start, end, box:{x,y,width,height}, color_rgb, thickness}]
```

highlights 可空；box 使用原源坐标，必须完全在 crop 内。start/end 是源秒数，thickness 是缩放前像素，颜色为六位十六进制 RGB。固定矩形仅提示注意，不改变软件状态，也不是光标的真实轨迹。没有自动决定焦点或检测 UI 的逻辑。

输出 focused.mp4、focus-map.json，坐标转换为 `(source_x-crop.x)*output.width/crop.width` 及对应 y。只处理视频画面，原音轨 stream copy；输出没有剪掉等待时间。派生视频重新计算哈希，并通过回执保留源身份。

## tutorial-plan-compile

```text
operation: tutorial-plan-compile
plan: ExecutionPlan
expected_revision: fingerprint(plan)
steps: [{
  id, label, context_id, requires:[step_id],
  before: EventWindow, action: EventWindow, result: EventWindow
}]
result_cues: [{id, step_id, start, end, text}]   # 成片秒数，可空

EventWindow = {
  clip_id, start, end,                         # 该 clip 对应的源秒数
  min_visible_seconds,                        # 复杂层决定的正数
  evidence:{path,sha256}                      # 已审阅帧/日志/记录文件
}
```

每个事件必须完整保留在指定 clip；执行计划的帧数取整若导致尾部截短，拒绝。before.end ≤ action.start ≤ action.end ≤ result.start，同样约束映射后的输出时间；不是要求连续无等待。剪掉中间等待可将三个窗口放入同一源的多个 clip，但复杂层仍须标明省略，不能据压缩后时长宣称产品响应速度。

requires 声明步骤的结果结束时间必须不晚于当前 action 开始；所有正时长事件的时间约束排除循环依赖。各 step 共用 context_id 仅是声明身份，编译器不会自动证明录屏确属同一个案例。

result_cues 从结果开始到结果结束内显示，避免提示先于证据。计划未登记的其他字幕、预览或 TTS 不受本规则自动检查，最终语义检查必须覆盖它们。

输出 execution-plan.json 和 tutorial-proof-map.json，后者保留证据身份、源/输出映射、依赖与检查边界。只有字节、时序、覆盖通过；真实软件行为、教学完整性、文字可读性、视听质量另行验收。

## 当前能力限制

固定区域聚焦与已有录屏切片可以执行；录屏采集、OCR、光标轨迹采集、连续镜头运动和 NLE 工程适配尚未实现。真实网页交互使用当前宿主支持的浏览器工具，不能把合成 UI、屏幕截图动画或预设回放标为原生录屏。缺素材可交脚本/拍摄单，完整制作不得据此宣称交付完成。

### screen-focus：显式展示坐标（可选）

旧请求不变：缺省crop、highlight.box、thickness均为未裁切源视频像素。
可选新增：

```json
{"coordinate_space":{"kind":"display","width":960,"height":540,"source_width":1920,"source_height":1080}}
```

这声明展示图是**完整源画面未经裁切、旋转、镜像或加边框/黑边的一次等比缩放**。
不是视口、网页截图或自动UI识别；无法满足此声明时使用明确源坐标，不猜测偏移。
source_width/height必须与本次实际probe一致；所有尺寸为正整数，拒绝bool。
展示宽高比必须与源一致。使用精确分数将crop、全部highlight.box及thickness
统一映射到源像素，任何非整数结果都拒绝，不四舍五入；随后仍执行原偶数crop、
范围、线宽、旋转/SAR及等比输出校验。output始终是最终视频像素，不随展示比例解释。

focus-map的crop、highlights及coordinate_mapping始终保存**解析后的源坐标语义**。
展示调用另有coordinate_audit，保留原声明、原输入矩形与线宽、probe源尺寸及精确
比例分子/分母。审计只证明转换关系，不认证展示图来源、选区正确、UI事实或教学效果。
例如display960×540的x130/y180/w670/h335映射到1920×1080源的x260/y360/w1340/h670。

输出读回核实际视频尺寸、方形像素、音轨数量/顺序及codec/sample-rate/channels与源
一致（音频copy，视频仍重编码），末尾复核源SHA后才发布成功focus-map。
output_readback只报告元数据匹配，不等同解码波形、听审或原视频像素无损保持。
失败可留下诊断媒体文件，但不发布成功map，不自动转码/重试/改容器。
当前仍只有默认focused.mp4，无新增容器选择；本环境已实测PCM_s16le以ipcm写入MP4可行，
不将“PCM必须转AAC”作为跨环境事实。
