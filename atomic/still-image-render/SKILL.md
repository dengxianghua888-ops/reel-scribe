---
name: still-image-render
description: 按明确帧数、帧率、画幅和裁切关键帧把单张图片渲染成静止或运镜视频；不设计镜头、不选择图片、不生成主体运动。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 明确静图运镜

提供 operation=still-image-render、source={path,sha256}、frames、fps、width、height、crop_keyframes、interpolation、background_rgb、allow_upscale、input_color=srgb或bt709。关键帧每项为frame和rect=[源像素x,y,width,height]，从0到frames−1完整覆盖，严格递增。每个矩形在源内且与输出等比例。linear／smoothstep只按给定路径插值，不改变画面内容。

输入为单帧PNG/JPEG/WebP的RGB/RGBA/L/LA；alpha按明确RGB背景合成。嵌入ICC、EXIF旋转、CMYK和动画图需上游显式规范化，不自动猜色彩或朝向。放大须显式allow_upscale。需要Pillow与FFmpeg；输出H264/yuv420p，按声明标sRGB或BT709传递函数，BT709原色及YUV矩阵（标签同时写在帧上，不依赖FFmpeg输出选项）；来源解释为调用者声明，不认证色彩母版，无声音。色彩原子只接受BT709传递函数：sRGB标记的输出会被color-profile-scan和color-lut-apply以元数据冲突拒绝；要进入色彩链，须由调用者改为声明bt709，即照片码值不做传递函数转换、按BT.709显示码值解释，并在作品notes中写明这一解释（真实照片实测见[色彩层真实素材操作记录](../../docs/color-real-run-20261119.md)）。

输出still-motion.mp4、逐帧crop-path.json与still-motion-map.json。检查实际解码帧数、恒定帧钟、几何、源hash未改。此为静图裁切动画，不称图生视频模型、光流、3D视差或画内动作。实际主体保护、运动速度、阅读时间、重采样清晰度和完整播放由复杂层评判。

图片选择、焦点与运镜方向交给复杂层；参数缺失不自动中心裁切。将源图→明确运镜→作品时间线的版本链保存；局部修改生成新视频并在同一作品中通过scope替换。实现见[still_ops.py](../../runtime/still_ops.py)。
