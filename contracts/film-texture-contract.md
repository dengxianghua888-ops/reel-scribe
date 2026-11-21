# 胶片质感（film-texture/1）

`film-texture-apply` 对已声明 BT.709 或 sRGB SDR 的视频施加显式参数的光晕、暗角和颗粒。它不选风格，也不声称模拟任何胶片型号。

## 请求

| 字段 | 约束 |
|---|---|
| `source` | `{path, sha256}`；结束时复核字节未变。只处理第一条视频流（渲染与读回相同）。宽高必须为偶数；不能带旋转元数据（`ROTATED_TEXTURE_SOURCE_UNSUPPORTED`）；必须是零起点恒定帧率：`avg_frame_rate` 与 `r_frame_rate` 相等且在 (0, 120] 内（`TEXTURE_CFR_REQUIRED`），第 i 帧时间戳与 i / fps 相差不超过 10 µs（`TEXTURE_ZERO_ORIGIN_CFR_REQUIRED`）。非方形像素可以接受，样本宽高比（SAR）写回输出 |
| `input_color` | `{space: bt709-sdr \| srgb-sdr, range: limited, basis}`，按[色彩特征合同](color-profile-contract.md)的规则校验标签 |
| `effects` | `halation`、`vignette`、`grain` 中至少一个，见下 |
| `readback_frames` | 1–4 个不重复的帧号 |

**效果参数**：

| 效果 | 字段 | 范围 | 计算 |
|---|---|---|---|
| `halation` | `threshold` | 0.5–0.98 | 在线性光中，用亮度码值超过阈值的部分作高光（smoothstep 过渡） |
| | `radius_px` | 1–64 | 取高光的最大通道，做近似高斯模糊（σ = 半径 / 2） |
| | `strength` | (0, 1] | 光晕亮度 × `strength` × `tint`，加回线性光 |
| | `tint` | 每通道 0–1，至少一个大于 0 | 光晕的颜色；红橙色接近传统的胶片光晕 |
| `vignette` | `strength` | (0, 0.8] | 在线性光中按到画面中心的归一化距离压暗，角落最多压暗 `strength` |
| | `start` | [0, 1) | 从该距离开始压暗，smoothstep 过渡 |
| `grain` | `amount` | (0, 0.08] | 在码值上叠加零均值噪声，标准差为 `amount` |
| | `size_px` | 0–4 | 噪声做近似高斯模糊（σ = `size_px` / 2）后重新归一化到 `amount`；0 表示逐像素噪声 |
| | `mode` | `luma` \| `rgb` | `luma`：三通道加同一噪声；`rgb`：三通道各自独立 |
| | `midtone_weighted` | 布尔 | 为真时噪声乘以 4·Y·(1−Y)，暗部和高光的颗粒更少 |
| | `temporal` | `per-frame` \| `static` | 逐帧种子为 `seed + 7919 × 帧号`，或每帧相同 |
| | `seed` | 0–2³²−1 | 显式种子 |

**顺序固定**：光晕 → 暗角 → 颗粒。近似高斯模糊由三次可分离盒式模糊组成，边缘采用反射处理。

## 管线

源视频以 16 位 RGB 全分辨率解码，numpy 逐帧计算，再经 FFmpeg 编码为 4:2:0：libx264 CRF 12、`-tune grain`，写入与输入相同的 BT.709 或 sRGB 标签，音轨原样复制。原始帧不带时间戳，编码端按同一帧率重新打时间戳，所以输入限定为零起点恒定帧率；原始帧同样不带 SAR，编码时用 `setsar` 写回源的 SAR（源未声明时不写）。输出的帧数、每帧时间戳和 SAR 都必须与源一致（`TEXTURE_FRAME_COUNT_CHANGED`、`TEXTURE_OUTPUT_CLOCK_MISMATCH`、`TEXTURE_OUTPUT_SAR_MISMATCH`）。YUV 与 RGB 之间的转换使用 swscale 的 `accurate_rnd+full_chroma_int`：默认取整会让 RGB48 → 4:2:0 的直通往返整体偏暗约 0.006（约 8 位下 1.5 个码值）。

**监督**：解码、编码两个 FFmpeg 进程各在独立进程组中运行，FFmpeg 的错误输出写入运行目录的 `decode.log`、`encode.log`。监督线程在调用方取消，或连续 300 秒没有完成一帧时，结束这两个进程组；这也会打断阻塞在管道读写上的主线程。结果分别为 `TEXTURE_CANCELLED`（回执标记 `cancelled`）和 `TEXTURE_STALLED`，已写出的部分输出保留。读回解码受同样的监督；选中的帧可能相隔很远，其间没有输出，所以读回以 FFmpeg 每 0.5 秒刷新一次的进度报告（`-progress`）作为进展。

## 读回

在指定帧上，用同一套计算对解码后的源帧重算预测值，并与解码后的输出比较：

- **门禁**：预测与输出各做 σ = 1.5 像素的低通后，ΔE2000 中位数不超过 3，否则 `TEXTURE_READBACK_MISMATCH`。逐像素的颗粒在 4:2:0 有损编码后无法一一对应，所以门禁比较低通后的图像；未低通的中位数另作参考报告。
- **逐效果测量**：重算“去掉该效果”的预测，用输出减去它，得到该效果在输出中的实际贡献，与预测的贡献对比：
  - 光晕：三个通道平均增加的光；
  - 暗角：角落与中心的亮度比（去掉暗角、预测、输出）；
  - 颗粒：亮度噪声的标准差（预测、输出），以及两者均值的差。

## 输出 `film-texture.json`

视频路径与哈希、生效的参数与顺序、读回结果，`film_stock_claim: NONE`。

## 不能据此声称

- 效果是参数化近似，不是任何胶片型号的测量或仿真。
- `rgb` 模式的色度噪声在 4:2:0 输出中大多丢失，`luma` 模式保留得更好。
- 读回只覆盖指定帧。
- 光晕半径和颗粒大小按编码像素计算；非方形像素时，它们在屏幕上不是圆形。
- 是否好看、适不适合内容，需要人看预览决定。
