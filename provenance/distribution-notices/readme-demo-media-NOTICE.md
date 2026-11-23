# 首页演示素材来源

`docs/assets/readme/` 中的演示图片与视频（`banner.jpg`、`workflow.jpg`、`grade.jpg`、`texture.jpg`、`log.jpg`、`look.jpg`、`captions.jpg`、`showcase.webp`、`showcase.mp4`）使用以下素材制作。

## 画面

- **来源**：Netflix Open Content 短片《Sparks》，© Netflix, Inc.，按 [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/) 许可提供。
  - 动态画面取自 `https://s3.amazonaws.com/download.opencontent.netflix.com/sparks/sdr/Sparks_SDR_UHD_4096x2160_5994fps.mov`。
  - Log 对比画面取自同一来源 `sparks/aces_image_sequence_59_94_fps/` 下的 ACES 帧。
- **改动**：
  - 截取 100、108、148、156、180、76 秒起各约 3.5 秒，缩放为 1920×1012、29.97 fps 并重新编码。
  - 用本库的原子操作套用调色层、胶片质感（光晕、颗粒、暗角）与中文字幕。
  - Log 对比画面由 ACES 帧经 OpenColorIO 编码为 S-Log3，再用 `color-log-transform` 转回 Rec.709。
  - 加入说明文字、对比分屏和片尾标题。
- 这些改动不代表 Netflix 或原作者认可本项目。

## 文字

图中说明文字用 Noto Sans CJK SC 渲染（SIL Open Font License 1.1）；字体文件不随仓库分发。

## 示意图

`workflow.jpg` 中的对话与步骤是使用示例，不是某一次运行的完整日志。
