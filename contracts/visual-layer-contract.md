# 显式视频叠层合同 v1

实现：[overlay_ops.py](../runtime/overlay_ops.py)。请求字段为 operation=visual-layer-render、source={path,sha256}、input_color=bt709-sdr-limited、layers（非空列表）。

每层字段：id、source={path,sha256}、source_start_frame、start_frame、duration_frames、rect=[x,y,width,height]、opacity、z、allow_upscale、input_color=bt709-sdr-limited。

- 帧号为零基整数，duration_frames>0，区间 [start_frame,start_frame+duration_frames)。输出第 n 帧使用 source_start_frame+n-start_frame 帧，不自动补尾或循环。
- 输入为单视频流、零起点 CFR、相同有理帧率、方形像素、无旋转的 yuv420p。BT709 SDR limited 标签冲突拒绝；缺标签依调用者声明，不代表测量色彩正确。
- rect 四值为偶数，宽高至少2且全在底片内，与源视频严格等比例；放大须 allow_upscale=true。裁切/规范化在上游显式完成。
- opacity 在0到1之间；z 为唯一整数，数值越大越靠上。补充视频音轨不混入，底片所有音轨编码载荷保持。
- 叠层全程保持 YUVA：缩放显式使用 BT.709 矩阵与有限范围，不透明度直接缩放 alpha 平面，不经 RGB 往返。早先版本用 colorchannelmixer 调不透明度，会隐式经过 BT.601/709 不一致的 RGB 转换，使彩色叠层偏色（如 (30,180,40) 变为 (14,155,32)），灰色不受影响。
- 输出 H264 重编码，底片帧数、尺寸、帧率与解码时钟保持；叠层外像素不保证逐字节不变。返回逐层映射、音轨检查和输出哈希。

## 同一作品

WorkDocument 可选 visual_layers 为 ID 字典。层值不带 id/start_frame，改为 anchor_clip_id（片段ID或null）与 offset_frames；输出起点为锚点输出首帧加 offset_frames，null 时相对全片。负偏移只在最终范围合法时允许。

增删改层需 scope.visual_ids。主轨变化使叠层窗口下的源内容改变时，也须列入 visual_ids 复核；锚点随前文缩短而移动且覆盖同源内容时可保持。画幅、帧率、fit变化须复核所有层。声明复核范围不证明解释正确或人物可见。

work-render 顺序为主轨→调色（有调色段时）→混音→叠层→字幕→技术检查，叠层不被调色；output-visual-layers.json 保留消费映射。证据映射报告 visual_layer_intersections，仅说明时间交叠；原素材被覆盖不能继续用时间覆盖率冒充可见性。完整观看、听检与原生编辑器验收分别记录。

## 候选预览

W04 局部修改的候选预览与正式 work-render 使用同一完整 WorkDocument 渲染顺序：主轨→混音→叠层→字幕→QC。`work-render.preview_candidate` 只消费哈希绑定的 `work-candidate/1`，不提交作品头；预览回执记录候选文档哈希、叠层映射与当前头是否仍匹配。外部编辑器可用自身隔离预览，但须读回全部层和项目修订，不要求转换为本库 SQLite。
