# 相机 Log 输入的显式转换（color-log-transform/1）

`color-log-transform` 把调用者声明的相机 Log 视频（Apple Log、S-Log3、V-Log、ARRI LogC 等），经带版本号的 OpenColorIO（OCIO）内置配置，按调用方选择的显示与视图转换为 BT.709 或 sRGB SDR。相机、码值范围、YUV 矩阵和视图都由调用方决定；本原子不猜测、不自动选择，也不评价观感。

需要 `opencolorio` Python 包（BSD-3）。没有安装时报 `COLOR_LOG_OCIO_REQUIRED`。

## 请求

| 字段 | 约束 |
|---|---|
| `source` | `{path, sha256}`；结束时复核字节未变 |
| `input` | `{colorspace, matrix: bt2020nc \| bt709, code_values: full \| video}`，见下 |
| `ocio` | `{config, display, view}`，见下 |
| `lut_size` | 33 或 65 |
| `output_pix_fmt` | `yuv420p` 或 `yuv420p10le` |
| `sample_frames` | 1–8 个不重复的帧号，用于读回和测量 |

**输入声明**：
- `colorspace`：配置中的相机 Log 色彩空间名，必须是 `Input/` 族、编码为 `log` 的非数据空间，例如 `Apple Log`、`Apple Log 2`、`S-Log3 S-Gamut3.Cine`、`V-Log V-Gamut`、`ARRI LogC4`、`CanonLog3 CinemaGamut D55`、`D-Log D-Gamut`。ACEScct 这类工作空间不算相机输入，拒绝。
- `matrix`：Y'CbCr 到 RGB 的矩阵。文件的 `color_space` 标签缺失时接受声明；与声明冲突时以 `COLOR_LOG_MATRIX_CONFLICT` 拒绝。
- `code_values`：Log 曲线定义所用的码值与文件样本的对应关系。`full` 表示样本按全范围解释（10 位码值 ÷ 1023），`video` 表示按视频范围展开（64–940 映射到 0–1）。各家曲线大多按全范围码值定义，例如 Apple Log 的 18% 灰约为 10 位码值 500，S-Log3 为 420，V-Log 为 433；但文件的范围标签不一定可靠，所以必须声明。声明与文件的范围标签不同时，`warnings` 会记录，但照声明执行。
- 只接受 10 位或 12 位的 4:2:0、4:2:2、4:4:4 YUV；8 位 Log 拒绝（`COLOR_LOG_PIXEL_FORMAT_UNSUPPORTED`）。
- 带 HLG、PQ 传递函数标签的文件拒绝（`COLOR_LOG_HDR_TRANSFER_CONFLICT`），这类素材用 [color-input-transform](color-input-transform-contract.md)。
- 相机 Log 没有标准的传递函数标签，文件常常不带标签或标成 bt709。其他标签只记录、不采信，结果的 `input_basis` 恒为 `caller-declared`。

**OCIO 配置与视图**：
- `config` 只接受带版本号的内置配置，例如 `ocio://studio-config-v5.0.0_aces-v2.1_ocio-v2.6`。内置配置的内容随 OCIO 版本固定；`-latest`、`default` 这类会随升级变化的别名，以及配置文件，目前都拒绝（`COLOR_LOG_CONFIG_UNSUPPORTED`）。配置文件可能引用外部 LUT，单个文件的哈希不能绑定全部内容。
- `display` 为 `Rec.1886 Rec.709 - Display`（输出标签 bt709）或 `sRGB - Display`（输出标签 iec61966-2-1）；HDR 与广色域显示拒绝。
- `view` 必须是该显示在配置中列出的视图，例如 `ACES 2.0 - SDR 100 nits (Rec.709)`（有色调映射）或 `Un-tone-mapped`（不做色调映射，场景线性直接按显示编码，超出显示范围的部分被裁剪）。

## 转换链

1. OCIO 按“Log 色彩空间 → 显示/视图”建立处理器（`OPTIMIZATION_LOSSLESS`）。
2. 在 Log 码值的 `lut_size`³ 网格上求值，裁剪到 [0,1] 后写成 `log.cube`。
3. FFmpeg：`zscale` 按声明的矩阵和码值范围把 Y'CbCr 转为 32 位浮点 RGB → `lut3d`（四面体插值）→ BT.709 矩阵、有限范围 → 写入 BT.709 原色与所选显示的传递函数标签。
4. libx264 CRF 18 编码，`-fps_mode passthrough` 保持帧时序，音轨原样复制。完整滤镜串写在结果的 `filter` 中。

Y'CbCr 到浮点 RGB 用 `zscale`，不用 `scale`：实测 swscale 转浮点 RGB 时把大于 1.0 的值截掉，会抹掉超白码值，也会让下面的码值测量看不出范围声明错误。cube 的定义域是 [0,1]，超出的码值在套用时被裁剪。

## 测量与读回

- **烘焙误差**：在 4096 个固定伪随机 Log 码值上，比较精确处理器与 cube 四面体插值（两者都裁剪到 [0,1]），报告 ΔE2000 中位数、p95 和最大值；网格点超出显示范围的比例另行报告。
- **读回门禁**：在采样帧上，按声明解码源（全分辨率转换后逐点取样，最宽 256），把码值裁剪到 [0,1] 后用精确处理器预测，与解码后的输出比较。ΔE2000 中位数不超过 2，否则 `COLOR_LOG_READBACK_MISMATCH`。
- **源测量**：
  - 码值超出 [0,1] 的像素比例和 0.1/99.9 分位码值。比例超过 1% 时，`warnings` 提示检查 `code_values`：把全范围文件当成视频范围解码，高光会落到 1 以上。
  - 精确处理后超出显示范围、被裁剪的像素比例；超过 1% 时提示。`Un-tone-mapped` 视图下高光通常会触发这一项。
- **输出核对**：输出必须带 BT.709 原色和矩阵、所选显示的传递函数、有限范围标签，帧数必须与源一致，否则报 `COLOR_LOG_OUTPUT_TAGS_UNEXPECTED` 或 `COLOR_LOG_FRAME_COUNT_CHANGED`。
- **输出 `color-log-transform.json`**：视频与 cube 的路径和哈希、生效的声明、OCIO 版本与配置名、配置和处理器的缓存 ID、烘焙误差、读回、测量、提示，以及 `output_interpretation: {space: bt709-sdr | srgb-sdr, range: limited, basis: verified-metadata}`，供后续原子直接使用。

## 不能据此声称

- 色彩空间、码值范围和矩阵是调用方的声明；文件里没有能证明“这是某种相机 Log”的标签。
- 视图是调用方的选择，换一个视图画面就不同；没有“正确”的 Log 转 SDR。
- 码值超出 [0,1] 和超出显示范围的部分都被裁剪，比例见测量结果。
- 读回只覆盖采样帧；cube 是对处理器的采样，误差见烘焙误差。
- 测试与真实内容实验都用 OCIO 合成的 Log 素材；没有用真实相机拍摄的 Log 文件验证过文件标签与范围的实际情况。
