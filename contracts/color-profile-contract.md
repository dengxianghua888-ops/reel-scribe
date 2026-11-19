# 色彩特征测量（color-profile/1）

`color-profile-scan` 对已声明 BT.709 SDR 的视频做**显式采样**测量，返回数值证据。它不调色、不选风格、不检测人脸或肤色，也不给出审美分数。

## 请求

| 字段 | 约束 |
|---|---|
| `source` | `{path, sha256}`，绝对路径；结束时复核字节未变 |
| `start` / `end` | 源时间区间，`start < end ≤ duration` |
| `samples` | `{mode: interval, interval_seconds ≥ 0.01}` 或 `{mode: times, times: [严格递增, 位于 [start,end)]}` |
| `max_samples` | 1–600；请求样本数超过即拒绝（`COLOR_PROFILE_SAMPLE_LIMIT`），不抽稀 |
| `analysis_size` | `[width, height]`，每边 8–512；swscale area 缩小 |
| `input_color` | `{space: bt709-sdr, range: limited 或 full, basis: verified-metadata 或 caller-declared}` |
| `palette_colors` | 1–8 |
| `regions`（可选） | 至多 16 个 `{id: [x0, y0, x1, y1]}`，0–1 归一化矩形，由调用者声明含义 |

`verified-metadata` 要求 `color_transfer`、`color_primaries`、`color_space` 为 bt709，`color_range` 与声明一致；`caller-declared` 允许缺失标签但拒绝冲突标签。HLG（arib-std-b67）、PQ（smpte2084）、BT.2020/P3 原色拒绝；yuvj 像素格式要求声明 full。支持 8/10 位 4:2:0、4:2:2、4:4:4 YUV。

## 解释链

BT.709 Y'CbCr → FFmpeg swscale area 缩小到全范围 8 位 R'G'B' → BT.1886 EOTF（γ2.4，Lw=1，Lb=0）线性化 → BT.709 原色到 CIE XYZ（D65）→ CIELAB。显示环境是**声明的假设**，不是测得的显示器。

## 输出 `color-profile.json`

- `aggregate`：所有样本像素合并后的 Y' 均值与 p01/p05/p50/p95/p99；剪切比例（任一通道 ≥254、三通道均 ≤1）；CIELAB 均值；色度均值/p50/p95；Hasler–Süsstrunk 鲜艳度；中性像素（C*<10 且 20≤L*≤90）的 a*/b* 均值与占比；灰世界线性比 R/G、B/G；12 段色相直方图（仅 C*≥8 的像素）。
- `palette`：CIELAB k-means（最大最小初始化、固定步长子样本、至多 25 轮），中心、占比和按同一假设换算的显示色值。
- `samples`：每个请求时刻的紧凑统计和解码帧 rgb24 SHA-256；帧由解码器选取请求时刻及之后的第一帧。
- `temporal`：样本均值 CIELAB 的相邻 ΔE76 最大值与均值、L/a/b 标准差。这是样本级漂移，不是逐帧闪烁。
- `regions`：声明区域的 CIELAB 均值、均值色度与色相、BT.709 Cb/Cr 矢量示波角及相对约 123° 肤色参照线的偏移。
- `aesthetic_judgement: NOT_PROVIDED`、`skin_detection: NOT_PERFORMED` 与限制说明。

原始解码帧读取后删除，回执只保留其哈希。比较不同素材时应保持相同 `analysis_size`、采样密度与区间语义；统计只代表采样帧。
