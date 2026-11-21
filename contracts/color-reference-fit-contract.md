# 参考色彩迁移拟合（color-reference-fit/1）

`color-reference-fit` 把目标素材的色彩统计向参考靠拢，并把结果拟合成可编辑的调色参数。链路是规划中的“统计目标 → 拟合到可编辑参数 → 编译 LUT → 预览”的前两步：它只产出候选，不编译、不套用、不采用，也不声称结果像参考。

## 请求

| 字段 | 约束 |
|---|---|
| `reference` / `target` | `{source: {path, sha256}, input_color, frames}`。`input_color` 按[色彩特征合同](color-profile-contract.md)的规则校验；`frames` 为 1–32 个不重复的帧号，均在视频帧数内 |
| `method` | `reinhard-lab`、`mvgd` 或 `histogram` |
| `grade_id` | 草案调色层的 ID，规则同 color-grade-compile（不得含引号、换行或 `#`） |

参考和目标的解释可以不同（例如 sRGB 照片参考、BT.709 视频目标）：参考像素先经 CIELAB 换算到目标解释的码值，所有方法都在目标的码值域中计算，草案的 `interpretation` 与目标一致。

## 方法与拟合

样本帧按最宽 256 的分析尺寸逐点取样，再均匀抽取至多 20000 个像素参与计算。

| 方法 | 理想迁移 | 拟合为 |
|---|---|---|
| `reinhard-lab` | CIELAB 每个通道 `(x − μt)·σr/σt + μr`；σt 下限 0.5，避免把近乎平坦的通道无限拉伸 | ASC CDL |
| `mvgd` | Pitié 的 MKL 映射：`T = Σt^-½ (Σt^½ Σr Σt^½)^½ Σt^-½`，`x' = T(x − μt) + μr`，在 RGB 码值上计算，协方差加 1e-6 的对角正则 | ASC CDL |
| `histogram` | 每个通道按秩把目标分位数映射到参考的同一分位数 | 逐通道曲线，17 个固定控制点，单调不减 |

- **CDL 拟合**：power 固定为 1。在 [0.05, 2] 上对饱和度做黄金分割搜索，目标是 CIELAB 平方误差；每个候选饱和度先撤销饱和度步骤，再用逐通道最小二乘求出对应的 slope、offset。斜率和饱和度都会拉开各通道的离散程度，交替求解会让斜率吸收饱和度变化，所以每次都重新求解。参数裁剪到 color-grade-compile 的取值范围。
- **曲线拟合**：在 17 个等距码值处插值匹配映射，强制单调不减；观测范围以外保持最近的映射值。
- 草案用 color-grade-compile 的解析链复算一遍，与拟合结果的 ΔE2000 必须小于 0.05，否则 `COLOR_FIT_GRADE_MISMATCH`。

## 输出 `color-reference-fit.json`

- `grade`：`color-grade/1` 草案，只含一个 `cdl` 或 `curves` 操作；`adopted: false`，`strength: NOT_CHOSEN`。
- `distances_to_reference`：`before`（目标原样）、`ideal_transfer`（统计迁移的理想结果）、`fitted_grade`（草案的结果）三组与参考的距离：
  - `mean_color_delta_e2000`：两组像素平均 CIELAB 的 CIEDE2000；
  - `sliced_wasserstein_lab`：64 个固定随机方向上的一维 Wasserstein-1 均值；
  - `js_divergence_lab`：L*、a*、b* 各 50 格直方图 JS 散度（以 2 为底）的均值。
- `fit_residual_delta_e2000`：理想迁移与草案结果逐像素 ΔE2000 的中位数和 p95，表示可编辑参数能表达多少统计迁移。
- `method_details`：Reinhard 的均值与缩放、MKL 的线性映射矩阵。

## 不能据此声称

- 距离只比较采样帧的色彩分布，变小不等于“像参考”或更好看；统计量不看内容和构图。
- `histogram` 各通道独立匹配，可能改变色相；`mvgd` 会混合通道，CDL 只能用饱和度近似，残差如实报告。
- 草案是候选：强度、采用、保护项和是否预览由上层决定，经 color-grade-compile、作品调色与 color-consistency-check 后才进入作品。
