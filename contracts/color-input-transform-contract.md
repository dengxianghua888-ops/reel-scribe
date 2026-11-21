# HDR 输入的显式转换（color-input-transform/1）

`color-input-transform` 把调用者声明的 HLG 或 PQ（BT.2020）视频转换为 BT.709 SDR。素材类型、色调映射算子和峰值都由调用方决定；本原子不猜测、不自动选择，也不评价观感。

## 请求

| 字段 | 约束 |
|---|---|
| `source` | `{path, sha256}`；结束时复核字节未变 |
| `input` | `{transfer: hlg \| pq, range: limited \| full, basis: verified-metadata \| caller-declared}`。期望标签为 `arib-std-b67`（HLG）或 `smpte2084`（PQ）、`bt2020` 原色、`bt2020nc` 矩阵和对应范围。`verified-metadata` 要求标签齐全；`caller-declared` 允许缺失，但任何冲突标签都拒绝（例如 BT.709 标签的素材声明为 HLG） |
| `nominal_peak_nits` | 50–10000，传给 zscale 的 `npl`。PQ：该亮度映射为线性 1.0，即 SDR 参考白；HLG：zimg 按它做 HLG 的系统伽马与显示映射。常用 100 |
| `tonemap` | `{operator, desat, peak_nits?, param?}`。`operator` 为 `clip`、`mobius`、`hable`、`reinhard`、`linear`、`gamma`；`desat` 为 0–10；`clip` 以外的算子必须给 `peak_nits`（50–10000），按 `peak_nits / nominal_peak_nits` 传给 FFmpeg tonemap 的 `peak`；`param` 只用于 mobius、reinhard、linear、gamma |
| `output_pix_fmt` | `yuv420p` 或 `yuv420p10le` |
| `sample_frames` | 1–16 个不重复的帧号，用于测量 |

支持 8/10 位 4:2:0、4:2:2、4:4:4 YUV 输入。

## 转换链

`zscale` 按声明的传递函数、BT.2020 原色与矩阵线性化（`npl`）→ 32 位浮点 → `zscale` 转到 BT.709 原色 → FFmpeg `tonemap`（显式算子、`desat`、可选 `peak`、`param`）→ `zscale` 转为 BT.709 传递函数与矩阵、有限范围 → 写入 BT.709 帧标签。libx264 CRF 18 编码，`-fps_mode passthrough` 保持帧时序，音轨原样复制。完整滤镜串写在结果的 `filter` 中。

**为什么峰值必须显式**：峰值决定高光落在哪里。实测中，同一段最高只有 100 尼特的内容，按 1000 尼特峰值做 hable 映射，白色只剩 L* 62.7，整体明显变暗；不指定峰值时 FFmpeg 的默认值正是这种情况。`clip` 不需要峰值，但会把超过 SDR 参考白的部分直接裁掉。

## 测量与读回

- **采样帧测量**：在采样帧上（逐点取样，最宽 256），用与转换相同的线性化测量色调映射之前的源：
  - 峰值亮度：最大值、99.9 分位与 99 分位，单位尼特。4:2:0 色度在颜色边缘上采样会过冲，色块很多的画面里最大值可能比实际内容峰值高约两成，p99 更接近大面积亮部；
  - 超过 SDR 参考白 1% 以上的像素比例（1% 的余量用于吸收 10 位量化误差，白色本身不计入）；
  - 落在 BT.709 色域之外的像素比例：任一线性分量低于参考白的 −1%，这部分在转换后会被裁剪。阈值留出余量，量化和色度噪声造成的微小负值不计入。
- **峰值提示**：`peak_nits` 是实测峰值的两倍以上，或不到一半时，`warnings` 给出提示：前者会让中间调不必要地变暗，后者会裁掉高光。`clip` 遇到超白像素时同样提示。
- **输出核对**：输出必须带 BT.709 传递函数、原色、矩阵和有限范围标签，帧数必须与源一致，否则报 `COLOR_INPUT_OUTPUT_TAGS_UNEXPECTED` 或 `COLOR_INPUT_FRAME_COUNT_CHANGED`。
- **输出 `color-input-transform.json`**：视频路径与哈希、生效的参数、测量、提示，以及 `output_interpretation: {space: bt709-sdr, range: limited, basis: verified-metadata}`，供后续原子直接使用。

## 不能据此声称

- 算子与峰值是调用方的选择，换一个算子画面就不同；没有“正确”的 HDR 转 SDR。
- 测量只覆盖采样帧。
- 杜比视界 RPU 与 HDR10+ 动态元数据不读取，只转换基础层。
- BT.709 色域外的颜色在转换后被裁剪，比例见测量结果。
