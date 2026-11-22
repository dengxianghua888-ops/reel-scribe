# 相机 Log 输入的显式转换（color-log-transform/1）

`color-log-transform` 把调用者声明的相机 Log 视频（Apple Log、S-Log3、V-Log、ARRI LogC 等）转换为 BT.709 或 sRGB SDR。转换来自二者之一：

- **OCIO 模式**（`ocio`）：OpenColorIO 配置里“Log 色彩空间 → 显示/视图”的处理器。配置可以是带版本号的内置配置，也可以是调用方提供、按哈希绑定的 `.ocioz` 归档（例如厂商或调色师打包的配置及其 LUT）。需要 `opencolorio` Python 包（BSD-3），没有安装时报 `COLOR_LOG_OCIO_REQUIRED`。
- **厂商 LUT 模式**（`lut`）：调用方提供、按哈希绑定的 Log → 显示 `.cube`（例如相机厂商发布的 Log 转 Rec.709 LUT）。不需要 OCIO。

`ocio` 与 `lut` 必须恰好提供一个，否则 `COLOR_LOG_OCIO_OR_LUT_REQUIRED`。相机、码值范围、YUV 矩阵、视图或 LUT 都由调用方决定；本原子不猜测、不自动选择，也不评价观感。

## 请求

| 字段 | 约束 |
|---|---|
| `source` | `{path, sha256}`；结束时复核字节未变 |
| `input` | `{colorspace, matrix: bt2020nc \| bt709, code_values: full \| video}`，见下 |
| `ocio` | OCIO 模式：`{config, display, view}`，见下 |
| `lut_size` | OCIO 模式：烘焙 cube 的点数，33 或 65 |
| `lut` | 厂商 LUT 模式：`{cube: {path, sha256}, display}`，见下；此时不接受 `ocio` 与 `lut_size` |
| `output_pix_fmt` | `yuv420p` 或 `yuv420p10le` |
| `sample_frames` | 1–8 个不重复的帧号，用于读回和测量 |

**输入声明**：
- `colorspace`：OCIO 模式下是配置中的相机 Log 色彩空间名，必须是编码为 `log` 的非数据空间；内置配置还要求属于 `Input/` 族，例如 `Apple Log`、`Apple Log 2`、`S-Log3 S-Gamut3.Cine`、`V-Log V-Gamut`、`ARRI LogC4`、`CanonLog3 CinemaGamut D55`、`D-Log D-Gamut`，ACEScct 这类工作空间不算相机输入，拒绝。归档配置的族名由作者决定，只要求编码为 `log`。厂商 LUT 模式下它只是记录用的标签（非空字符串，否则 `COLOR_LOG_COLORSPACE_LABEL_REQUIRED`），LUT 本身决定转换。
- `matrix`：Y'CbCr 到 RGB 的矩阵。文件的 `color_space` 标签缺失时接受声明；与声明冲突时以 `COLOR_LOG_MATRIX_CONFLICT` 拒绝。
- `code_values`：Log 曲线定义所用的码值与文件样本的对应关系。`full` 表示样本按全范围解释（10 位码值 ÷ 1023），`video` 表示按视频范围展开（64–940 映射到 0–1）。各家曲线大多按全范围码值定义，例如 Apple Log 的 18% 灰约为 10 位码值 500，S-Log3 为 420，V-Log 为 433；但文件的范围标签不一定可靠，所以必须声明。声明与文件的范围标签不同时，`warnings` 会记录，但照声明执行。
- 只接受 10 位或 12 位的 4:2:0、4:2:2、4:4:4 YUV；8 位 Log 拒绝（`COLOR_LOG_PIXEL_FORMAT_UNSUPPORTED`）。
- 带 HLG、PQ 传递函数标签的文件拒绝（`COLOR_LOG_HDR_TRANSFER_CONFLICT`），这类素材用 [color-input-transform](color-input-transform-contract.md)。
- 相机 Log 没有标准的传递函数标签，文件常常不带标签或标成 bt709。其他标签只记录、不采信，结果的 `input_basis` 恒为 `caller-declared`。

**OCIO 配置与视图**：
- `config` 为带版本号的内置配置名，例如 `ocio://studio-config-v5.0.0_aces-v2.1_ocio-v2.6`，内容随 OCIO 版本固定；`-latest`、`default` 这类会随升级变化的别名拒绝（`COLOR_LOG_CONFIG_UNSUPPORTED`）。
- 或者为 `{path, sha256}` 指向的 `.ocioz` 归档（用 `ocioarchive` 或 `Config.archive` 打包）。归档把配置和它用到的全部 LUT 放在一个文件里，一个哈希即可绑定全部内容。普通 `.ocio` 文件可以引用文件之外的 LUT，单个哈希绑定不住，拒绝（`COLOR_LOG_CONFIG_ARCHIVE_REQUIRED`）。无法读取的归档报 `COLOR_LOG_CONFIG_ARCHIVE_INVALID`；归档缺少某个 LUT 时，建立处理器失败，报 `COLOR_LOG_PROCESSOR_UNAVAILABLE`。
- 归档先复制到私有临时目录，复制件的哈希与声明一致后才加载，转换用的 LUT 只来自复制件。OCIO 在进程内按 LUT 在归档内的路径缓存文件内容，两个归档里同名而内容不同的 LUT 会共用先读到的那份；因此建立处理器前后都清空 OCIO 缓存，并且同一进程内一次只建立一个处理器。
- `display` 为 `Rec.1886 Rec.709 - Display`（输出标签 bt709）或 `sRGB - Display`（输出标签 iec61966-2-1），且必须在配置中存在；HDR 与广色域显示拒绝。
- `view` 必须是该显示在配置中列出的视图，例如 `ACES 2.0 - SDR 100 nits (Rec.709)`（有色调映射）或 `Un-tone-mapped`（不做色调映射，场景线性直接按显示编码，超出显示范围的部分被裁剪）。

**厂商 LUT**：
- `cube` 按哈希绑定，必须是定义域 [0,1]、取值 [0,1]、2–65 点的 3D `.cube`（与 color-lut-apply 相同的解析规则；1D、带 shaper 或超出范围的 LUT 拒绝）。LUT 的输入必须是声明的 Log 码值，输出必须是所选显示的编码值：这只能由厂商文档保证，文件本身不说明。
- `display` 声明 LUT 输出的显示，取值同上，决定输出的传递函数标签和读回的比较方式。

## 转换链

1. OCIO 模式：OCIO 按“Log 色彩空间 → 显示/视图”建立处理器（`OPTIMIZATION_LOSSLESS`），在 Log 码值的 `lut_size`³ 网格上求值，裁剪到 [0,1] 后写成 `log.cube`。
2. 厂商 LUT 模式：校验过的 cube 字节原样写成 `log.cube`。
3. FFmpeg：`zscale` 按声明的矩阵和码值范围把 Y'CbCr 转为 32 位浮点 RGB → `lut3d`（四面体插值）→ `zscale` 转为 BT.709 矩阵、有限范围 → 写入 BT.709 原色与所选显示的传递函数标签。
4. libx264 CRF 18 编码，`-fps_mode passthrough` 保持帧时序，音轨原样复制。完整滤镜串写在结果的 `filter` 中。

Y'CbCr 与浮点 RGB 之间的转换都用 `zscale`，不用 `scale`：实测 swscale 转浮点 RGB 时把大于 1.0 的值截掉，会抹掉超白码值，也会让下面的码值测量看不出范围声明错误；它的浮点与全范围转换在 FFmpeg 6.1 与 8.0 之间结果也不同。cube 的定义域是 [0,1]，超出的码值在套用时被裁剪。

## 测量与读回

- **烘焙误差**（OCIO 模式）：在 4096 个固定伪随机 Log 码值上，比较精确处理器与 cube 四面体插值（两者都裁剪到 [0,1]），报告 ΔE2000 中位数、p95 和最大值；网格点超出显示范围的比例另行报告。厂商 LUT 本身就是转换，没有烘焙误差。
- **读回门禁**：在采样帧上，按声明解码源（全分辨率转换后逐点取样，最宽 256），把码值裁剪到 [0,1] 后预测输出：OCIO 模式用精确处理器，厂商 LUT 模式用该 cube 的四面体插值。与解码后的输出比较，ΔE2000 中位数不超过 2，否则 `COLOR_LOG_READBACK_MISMATCH`。
- **源测量**：
  - 码值超出 [0,1] 的像素比例和 0.1/99.9 分位码值。比例超过 1% 时，`warnings` 提示检查 `code_values`：把全范围文件当成视频范围解码，高光会落到 1 以上。
  - 预测输出超出显示范围、被裁剪的像素比例；OCIO 模式下超过 1% 时提示，`Un-tone-mapped` 视图下高光通常会触发这一项。厂商 LUT 的取值已在 [0,1] 内，这一项恒为 0。
- **输出核对**：输出必须带 BT.709 原色和矩阵、所选显示的传递函数、有限范围标签，帧数必须与源一致，否则报 `COLOR_LOG_OUTPUT_TAGS_UNEXPECTED` 或 `COLOR_LOG_FRAME_COUNT_CHANGED`。
- **输出 `color-log-transform.json`**：`mode`（`ocio` 或 `lut`）、视频与 cube 的路径和哈希、生效的声明、读回、测量、提示，以及 `output_interpretation: {space: bt709-sdr | srgb-sdr, range: limited, basis: verified-metadata}`，供后续原子直接使用。OCIO 模式另记 OCIO 版本、配置名、`config_origin`（内置配置名，或归档的路径与哈希）、配置和处理器的缓存 ID 与烘焙误差；厂商 LUT 模式另记 LUT 的路径、哈希、点数与显示，`look_selection` 为 `CALLER_CHOSEN_VENDOR_LUT`。

## 不能据此声称

- 色彩空间、码值范围和矩阵是调用方的声明；文件里没有能证明“这是某种相机 Log”的标签。
- 视图或厂商 LUT 是调用方的选择，换一个画面就不同；没有“正确”的 Log 转 SDR。厂商 LUT 是否真的对应声明的 Log 和显示，只能由其文档保证。
- 码值超出 [0,1] 和超出显示范围的部分都被裁剪，比例见测量结果。
- 读回只覆盖采样帧；cube 是对处理器的采样，误差见烘焙误差。
- 测试与真实内容实验都用 OCIO 编码的 Log 素材，包括由真实电影拍摄的场景数据编码的 Log；没有用相机写出的 Log 文件验证过文件标签与范围的实际情况。
- 视频范围的文件声明为 `full`、且文件没有范围标签时，回执发现不了这个错误：码值不会超出 [0,1]，也没有标签冲突。范围只能由上层按拍摄设置确认。
