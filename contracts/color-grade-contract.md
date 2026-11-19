# 参数化调色编译（color-grade/1）

`color-grade-compile` 把**明确参数**编译为 3D LUT 与交换文件。它不选择 look、不测量素材、不改媒体；套用使用 `color-lut-apply`。

## 请求

```json
{
  "operation": "color-grade-compile",
  "grade": {
    "schema": "color-grade/1",
    "id": "warm-soft-v1",
    "interpretation": "bt709-sdr-display",
    "ops": [
      {"type": "exposure", "stops": 0.3},
      {"type": "white_balance", "gains": [1.06, 1.0, 0.92], "preserve_luminance": true},
      {"type": "cdl", "slope": [1, 1, 1], "offset": [0, 0, 0], "power": [1, 1, 1], "saturation": 0.9},
      {"type": "lut", "source": {"path": "/abs/look.cube", "sha256": "…"}, "interpolation": "tetrahedral", "mix": 0.6}
    ],
    "strength": 0.8
  },
  "lut_size": 33,
  "exports": ["cube", "cc", "clf"]
}
```

| 字段 | 约束 |
|---|---|
| `grade.id` | 1–120 字符，不含引号或换行；写入 cube 标题和交换文件 ID |
| `grade.ops` | 1–16 个，按列出顺序执行 |
| `exposure.stops` | -4 到 4；线性光乘 2^stops |
| `white_balance.gains` | 线性光 RGB 增益，每项 0.25–4；`preserve_luminance=true` 时按 BT.709 亮度权重归一，使灰色亮度不变 |
| `cdl` | slope 0–4、offset -1–1、power 0.1–4、saturation 0–4；ASC CDL v1.2，SOP 与饱和度后均钳位 0–1（CLF `ASC_CDL style="Fwd"`） |
| `lut` | 来源按已验证字节解析，接受与 `color-lut-apply` 相同的 cube 子集；`interpolation` 为 tetrahedral 或 trilinear；`mix` 0–1，默认 1 |
| `grade.strength` | 0–1，默认 1；在代码值上 `input + strength × (chain − input)` |
| `lut_size` | 17、33 或 65 |
| `exports` | 必须含 `cube`，可加 `cc`、`clf`，不得重复 |

## 链模型

工作空间是显示参考的 BT.709 R'G'B' 代码值（0–1）。曝光与白平衡先按 BT.1886 γ2.4 线性化，乘增益并钳位，再编码回代码值。每个操作结束都钳位到 0–1：超出范围的信息被丢弃，不是柔和滚降。HDR、Log 与广色域不在本模型内。

## 输出

- `grade.cube`：红通道最快、绿次之、蓝最慢；值六位小数。
- `grade.cc`：仅当链恰为一个 CDL 且 strength=1，否则以 `COLOR_GRADE_CDL_NOT_REPRESENTABLE` 拒绝，且不写任何文件。回执写明钳位语义：不钳位实现（如 OpenColorIO `CDL_NO_CLAMP`）在超出 0–1 的区域不同。
- `grade.clf`：CLF v3。strength=1 且没有 mix<1 的 LUT 时为参数化链（Exponent、Matrix、Range、ASC_CDL、LUT3D），否则为编译 cube 的烘焙 LUT3D，回执 `mode` 区分。
- `color-grade.json`：规范化参数、`grade_sha256`、各文件哈希、链模型说明、`compiled_is_identity`，以及在 4096 个离网格点上比较解析链与本库四面体插值的 CIEDE2000 中位数、p95、最大值和最大代码值差。`applied_to_media=false`、`look_selection=NOT_PROVIDED`、`effect_review=NOT_RUN`。

## color-lut-apply 的强度

`color-lut-apply` 接受可选 `strength`（0 < s ≤ 1）。运行时在同一网格上派生 `identity + s × (lut − identity)`，写入 `selected.cube` 并在结果中记录派生 cube 的哈希；省略时 `selected.cube` 与已验证的输入字节完全相同。LUT 只读取一次，解析与套用使用同一份已哈希的字节。
