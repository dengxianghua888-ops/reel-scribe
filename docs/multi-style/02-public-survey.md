# 02 公开仓库调研：别人怎样组织风格、组件与评测

2026 年 11 月 26 日调研。完整清单（十类 53 个来源，另有 [12 章](12-open-evaluation.md)补充的 17 个，共 70 个；提交号、许可、借鉴与不借鉴）见 [catalog/public-survey.md](catalog/public-survey.md)，机器可读版见 [catalog/public-survey.json](catalog/public-survey.json)。研究库已有的 65 个剪辑器与 Agent 项目（OpenCut、CutVoke、Cutline、Concat、OpenStoryline 等），以及短剧仓库已有的 39 个导演与生成项目，本章不重复。

## 一、十类来源与各自的结论

| 类别 | 代表来源 | 对本方案最重要的结论 |
|---|---|---|
| A 同类产品与视频框架 | HyperFrames（Apache-2.0）、Remotion、Motion Canvas、Revideo | HyperFrames 是目前最接近“给 Agent 用的可改视频编辑器”的公开实现：210 个 block、239 个 component、18 个主题 token、按需求选运动机制的对照表、文字穿人的可测覆盖阈值、先测量再看片的审片顺序。它把“系列风格”做成 Pro 模板，说明风格本身是可以产品化的资产 |
| B 字幕动画 | pycaps、ai-video-captions、template-tiktok、PupCaps、pysubs2、libass、Aegisub | 逐词字幕已经有两条成熟路径：ASS 逐词标签（快、确定）与 CSS 渲染（排版强）。公开预设集中在“逐词高亮、弹入、大字冲击、极简、经典”几类，命名常用网红名，我们改用效果命名 |
| C 动效与组件库 | react-bits、Lottie（lottie-web/rlottie）、GSAP、anime.js、Theatre.js、Rive、Manim、editly | 文字动画的效果清单已很丰富（react-bits 33 种）；引擎各有所长，不存在一个引擎覆盖全部效果 |
| D 转场 | gl-transitions（主干 387 个）、ffmpeg-gl-transition | 转场数量不是问题，问题是按语义分组和限用；FFmpeg 自带 xfade 是固定集合，GLSL 转场需要额外滤镜 |
| E 视觉分析与合成 | SAM2（Apache-2.0）、RVM（GPL-3.0）、MatAnyone、CoTracker、EbSynth、PySceneDetect | 遮罩与跟踪是“机制包”的门槛。效果最好的几个（MatAnyone、CoTracker）是非商业许可，商用需另选或自训 |
| F 口播与短视频流水线 | FunClip、NarratoAI、MoneyPrinterTurbo、VideoLingo、auto-editor、ShortGPT、whisperX、FunASR | 这些是“能出片”的开源基线：规则剪静音、LLM 选段、自动配字幕。它们的产物正好用来定义默认基线（[09](09-baseline-eval.md)） |
| G 剪辑元素分类与数据集 | Edit3K、AutoTransition、MovieCuts、AVE、VEU-Bench、CutCraft | 剪辑元素已有成熟分类：组件 6 类、剪切 10 类、镜头属性 8 项、剪辑维度分帧内/镜内/镜间三层；CutCraft 给出“专家模型＋工具支撑的 VLM＋量表问答”的分层评测 |
| H 质量与评测 | VMAF、DOVER、VBench、VideoScore2 | 画质与生成质量有代理指标，但都不评“剪辑风格是否适合内容”；DOVER 为非商业许可 |
| I 摄影语言 | ShotBench、CameraBench（CC BY 4.0） | 景别、构图、角度、焦段、光线、运镜都有可标注的词表，适合给优质样本打标 |
| J 影调 | OpenColorIO、HaldCLUT 预设 | 影调可以按色彩空间严谨地做；公开 LUT 集合多为相同方式共享或无明确许可，只作参照 |

## 二、许可核对的直接影响

核对 LICENSE 文件后，有几项与直觉不同，直接改变实现选择：

| 项目 | 许可 | 影响 |
|---|---|---|
| MatAnyone、DOVER | S-Lab License 1.0，仅非商业 | 只作效果参照；商用人像抠像用 SAM2（Apache-2.0）或自有方案，画质代理用 VMAF 与自建量表 |
| CoTracker | CC BY-NC 4.0，仅非商业 | 跟踪类组件的商用实现需另选跟踪器 |
| RobustVideoMatting | GPL-3.0 | 可作为独立工具调用，不随包分发 |
| Remotion | Remotion License，公司许可另计 | 不作默认引擎；HTML 渲染路线以 HyperFrames（Apache-2.0）的做法为参照 |
| react-bits | MIT + Commons Clause | 只借效果清单，不复用代码 |
| auto-editor、EbSynth | 公有领域 | 可直接作为基线工具和转绘实验工具 |
| CutCraft、ShotBench、AVE、VEU-Bench、AutoTransition | 仓库无 LICENSE 文件 | 只借分类与评测方法，不分发数据 |

## 三、从调研合成的体系骨架

| 我们的对象 | 参照来源 | 合成方式 |
|---|---|---|
| 剪辑元素分层 | VEU-Bench 的帧内、镜内、镜间三层 | 帧内对应设计系统、影调、字幕；镜内对应画面运动、节奏中的镜长；镜间对应转场与剪切类型。评测题按这三层出 |
| 组件大类 | Edit3K 的 6 类、HyperFrames 的 block/component 标签 | 扩为 16 类、126 个组件（[04](04-motion-components.md)），每个组件声明首选与备选引擎 |
| 剪切词表 | MovieCuts 的 10 类 | 进入节奏刻面与方法卡的结构化字段，也作为优质样本的标注词表 |
| 镜头属性 | AVE 的 8 项、ShotBench 的 8 维、CameraBench 的运动分类 | 作为优质样本卡与风格帧的标注 Schema |
| 设计 token | HyperFrames 的 18 个主题 token | 保留调色板、字体、形状间距、运动四组，补中文排版组（每行字数、避头尾、数字与单位不拆行） |
| 字幕样式 | pycaps 12 个预设、ai-video-captions 6 种、HyperFrames 约 17 个字幕组件、ChatCut 49 款 | 去掉网红名与同义重复，按“分组 × 强调 × 动画 × 引擎”整理为 30 种 |
| 转场 | gl-transitions 387 个、FFmpeg xfade | 按语义归为 12 个转场组件，每个组件内部可挂多个着色器实现 |
| 运动机制 | HyperFrames 的 “The right mechanism” 表 | 写成组件的引擎选择规则：推近、平移、遮罩揭示、变速、定格各自有确定的实现位置 |
| 评测分层 | CutCraft 的 A/B/C 三种模式 | 技术测量 → 专家模型代理 → 工具支撑的模型评判 → 量表问答与人工盲评（[09](09-baseline-eval.md)） |
| 默认基线 | auto-editor、FunClip、pycaps 与 ai-video-captions 的“经典”样式 | 定义可复现的 B1 规则基线与 B2 开源最佳基线 |

## 四、明确不做的事

- 不以任何创作者、频道或品牌命名风格，不复刻其片头、字体组合或配色。
- 不把公开数据集打包进仓库；需要时按其原始条款各自下载。
- 不把“数量”当能力：387 个转场、3,094 个组件、580 张方法卡都只是候选空间，进入货架要过评测门槛。
