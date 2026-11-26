# 公开仓库调研表

2026-11-26 调研；提交号由 `git ls-remote` 取当日 HEAD，许可读自仓库 LICENSE 文件。“仅非商业”与“无 LICENSE 文件”的条目只作效果与方法参照，不进入商用实现。

## A 同类产品与视频框架（4）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes/tree/5b8bd85f3e2d09bb239eae2c96a855abe8e2e8f9) | `5b8bd85f3e2d` | Apache-2.0 | HTML/CSS/JS 逐帧渲染为确定性 MP4；210 个 block、239 个 component；18 个主题 token 契约；5 个系列风格模板（Pro）；13 个版式预设；字幕、叠层、运动、声音、审片参考 | 主题 token 契约的形状；“按需求选运动机制”的对照表；文字穿人覆盖 30–55% 的可测阈值；组件目录的标签化检索；先测量再看片的审片顺序 | 托管模板与 Pro 功能；模仿具体创作者频道的系列风格 |
| [remotion-dev/remotion](https://github.com/remotion-dev/remotion/tree/22976de0891795c4f0c61dc3921e953ad7f5d70b) | `22976de08917` | Remotion License：个人与小公司免费，公司许可另计 | React 写视频；字幕、模板生态最成熟 | 组件化写法与字幕时间模型 | 直接作为默认引擎（许可约束） |
| [motion-canvas/motion-canvas](https://github.com/motion-canvas/motion-canvas/tree/7b91435c301d530351dcf5ebb91dd139c002e405) | `7b91435c301d` | MIT | 生成器式程序化矢量动画 | 讲解图解、代码动画的引擎选项 | 实拍合成 |
| [redotvideo/revideo](https://github.com/redotvideo/revideo/tree/b5de67a009a55aa2768a1e178b0446b2479a0b4e) | `b5de67a009a5` | MIT | Motion Canvas 分支，增加渲染 API 与模板 | 服务端批量渲染图解 | — |

## B 字幕动画（7）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [francozanardi/pycaps](https://github.com/francozanardi/pycaps/tree/e2d36edfa08e3307d65b15bb20f17399dc2c9b40) | `e2d36edfa08e` | MIT | CSS 样式的逐词字幕；12 个预设（classic、default、explosive、fast、hype、line-focus、minimalist、model、neo-minimal、retro-gaming、vibrant、word-focus）；按标签条件着色 | 预设分组方式与“标签驱动强调” | 直接照搬预设命名 |
| [nicolaigaina/ai-video-captions](https://github.com/nicolaigaina/ai-video-captions/tree/bd87ac7ff1040f1364ab0d162bd59cb92fcdcc9c) | `bd87ac7ff104` | MIT | faster-whisper 词级时间 → pysubs2 生成 ASS 逐词动画；6 种流行样式（Hormozi、MrBeast、Karaoke、Minimal、Bounce、Classic） | ASS 逐词动画的实现路径；“Classic”作为基线参照 | 以网红名命名的样式 |
| [remotion-dev/template-tiktok](https://github.com/remotion-dev/template-tiktok/tree/e1e0d15bc9bddae2f49b97a7b09e9657dd5ad549) | `e1e0d15bc9bd` | 无 LICENSE 文件（依赖 Remotion 许可） | 逐词字幕模板，自动安装 whisper.cpp | 逐词高亮时间模型 | — |
| [hosuaby/PupCaps](https://github.com/hosuaby/PupCaps/tree/7318499828c419100bf42ef58cde7708dda352f0) | `7318499828c4` | Apache-2.0 | SRT 加 CSS3 动画渲染字幕 | 已有字幕文件时的样式化路径 | — |
| [tkarabela/pysubs2](https://github.com/tkarabela/pysubs2/tree/6371ae8bc2f9fed19aeb51a8e09d920e8bb86ce5) | `6371ae8bc2f9` | MIT | Python 读写 ASS/SRT | 字幕样式与时间操作 | — |
| [libass/libass](https://github.com/libass/libass/tree/841c52561c39df6767e3948efa8e5307efb11f1f) | `841c52561c39` | ISC | ASS 渲染器，影述 caption-burn 已使用 | 文字类组件的最快路径 | — |
| [TypesettingTools/Aegisub](https://github.com/TypesettingTools/Aegisub/tree/e63855b26fd9623bb5d4f461525383fb1f60cfdb) | `e63855b26fd9` | BSD 类 | 字幕编辑器与卡拉OK 模板器 | 卡拉OK 模板的效果分类 | — |

## C 动效与组件库（11）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [DavidHDev/react-bits](https://github.com/DavidHDev/react-bits/tree/a30a9da9b40a91c5672fc8cd77785719e8e5b1e6) | `a30a9da9b40a` | MIT + Commons Clause | 33 个文字动画（BlurText、DecryptedText、SplitText、TextType、ShinyText 等）及背景与微交互 | 文字动画的效果清单作为对照 | 代码复用（Commons Clause 限制售卖） |
| [airbnb/lottie-web](https://github.com/airbnb/lottie-web/tree/bede03d25d232826e0c9dca1733d542d8a7754fb) | `bede03d25d23` | MIT | 浏览器播放 AE 导出的 Lottie | 设计师资产与图标动画 | — |
| [Samsung/rlottie](https://github.com/Samsung/rlottie/tree/ea06d2f29ba01b8d06c00a838d107f5e484ae59b) | `ea06d2f29ba0` | MIT（含第三方组件） | C++ Lottie 渲染，可逐帧导出 | 无浏览器渲染 Lottie | — |
| [greensock/GSAP](https://github.com/greensock/GSAP/tree/5e6c35ff8eedea12d4f229129def635277d8b0f2) | `5e6c35ff8eed` | 无 LICENSE 文件（按官网条款） | 网页时间轴动画 | HTML 组件的时间控制 | — |
| [juliangarnier/anime](https://github.com/juliangarnier/anime/tree/01b81be1df6843ccfe0a71c0699a746bf740dd77) | `01b81be1df68` | MIT | 轻量动画库 | HTML 组件备选 | — |
| [theatre-js/theatre](https://github.com/theatre-js/theatre/tree/6ea82b938ea49609489f6377ded693ccc6ee8f5b) | `6ea82b938ea4` | Apache-2.0 | 可视化关键帧编排 | 需要人工微调关键帧的组件 | — |
| [rive-app/rive-runtime](https://github.com/rive-app/rive-runtime/tree/5afc38b151d1bd05528d02e180dbc01b7c49fab4) | `5afc38b151d1` | MIT | 状态机交互动画 | 可交互角色与图标 | 作为首批引擎 |
| [ManimCommunity/manim](https://github.com/ManimCommunity/manim/tree/18320e2f0feaf142b2c3a377068ddb44c82fb2a1) | `18320e2f0fea` | MIT | 数学动画 | 公式推导组件 | — |
| [mifi/editly](https://github.com/mifi/editly/tree/dc46674052eacd15ef6e0f563a58eb378b3804ad) | `dc46674052ea` | MIT | 声明式拼接、字幕与转场 | 简单批量模板 | — |
| [tnfe/FFCreator](https://github.com/tnfe/FFCreator/tree/abbbb1104f484278cc61c3be65408f2a6c7cc3a7) | `abbbb1104f48` | MIT | Node 视频合成与动画 | 批量图文成片参照 | — |
| [Zulko/moviepy](https://github.com/Zulko/moviepy/tree/211e4b15f6ce4f34a6a9efbfff40590e43a68f77) | `211e4b15f6ce` | MIT | Python 视频合成 | 原型验证 | 生产渲染 |

## D 转场（2）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [gl-transitions/gl-transitions](https://github.com/gl-transitions/gl-transitions/tree/22326e3d2099a0ccdbeeebd091d151182c2e7669) | `22326e3d2099` | MIT | 当前主干 387 个 GLSL 转场（npm 1.76.1 目录列 125 个） | 转场组件的着色器实现与命名参照 | 不加区分地全量上架（需按语义分组并限用） |
| [transitive-bullshit/ffmpeg-gl-transition](https://github.com/transitive-bullshit/ffmpeg-gl-transition/tree/3639b521aafb30b185de281f94560f298a22d420) | `3639b521aafb` | 无 LICENSE 文件 | 让 FFmpeg 使用 GLSL 转场的滤镜 | FFmpeg 链内的 GLSL 转场 | 要求自编译 FFmpeg 的部署 |

## E 视觉分析与合成（6）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [facebookresearch/sam2](https://github.com/facebookresearch/sam2/tree/2b90b9f5ceec907a1c18123530e92e794ad901a4) | `2b90b9f5ceec` | Apache-2.0 | 图像与视频分割 | 主体遮罩、文字穿人、分区调色 | — |
| [PeterL1n/RobustVideoMatting](https://github.com/PeterL1n/RobustVideoMatting/tree/53d74c6826735f01f4406b5ca9075eee27bec094) | `53d74c682673` | GPL-3.0 | 实时人像抠像 | 人物抠像的速度方案 | 随包分发（GPL） |
| [pq-yang/MatAnyone](https://github.com/pq-yang/MatAnyone/tree/e5ddc534c1fff9bb9e54cf476095d29071b7cb4f) | `e5ddc534c1ff` | S-Lab License 1.0（仅非商业） | 目标人像视频抠像 | 发丝与运动边缘的效果参照 | 商用集成 |
| [facebookresearch/co-tracker](https://github.com/facebookresearch/co-tracker/tree/82e02e8029753ad4ef13cf06be7f4fc5facdda4d) | `82e02e802975` | CC BY-NC 4.0（仅非商业） | 任意点跟踪 | 跟踪标签、实物线框的效果参照 | 商用集成（需另选商用许可的跟踪器） |
| [jamriska/ebsynth](https://github.com/jamriska/ebsynth/tree/2f5c97c0c21a86bb7334dee61453623e6a3d41c3) | `2f5c97c0c21a` | 公有领域（README 声明） | 关键帧引导的风格传播 | 转绘窗口的跨帧稳定 | — |
| [Breakthrough/PySceneDetect](https://github.com/Breakthrough/PySceneDetect/tree/facff3b7c4db4cd30ffcb7cd17a6d3262ebe2ec2) | `facff3b7c4db` | BSD-3-Clause | 切点检测 | B-roll 盘点、优质样本的平均镜长测量 | — |

## F 口播与短视频流水线（9）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [modelscope/FunClip](https://github.com/modelscope/FunClip/tree/cdcb53fe3d4b37365178ae4f779296e72b7beb6a) | `cdcb53fe3d4b` | MIT | Paraformer 转写＋按词稿或 LLM 选段剪辑 | 中文口播选段的对照基线 | — |
| [linyqh/NarratoAI](https://github.com/linyqh/NarratoAI/tree/29a11b6cdf61b69ba90321fc5babc160e0ca2657) | `29a11b6cdf61` | MIT | LLM 写解说、自动剪辑、配音字幕，支持短剧解说与混剪 | 影视解说与短剧解说的对照基线 | — |
| [harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo/tree/ff0d5f30693f78c31fc3fda36bfbbe8d8eebda98) | `ff0d5f30693f` | MIT | 关键词生成短视频（文案、素材、字幕、配音） | 图文与生成成片的对照基线 | — |
| [Huanshere/VideoLingo](https://github.com/Huanshere/VideoLingo/tree/d2d5a046d97526ae4950294cc5663ad520b22f52) | `d2d5a046d975` | Apache-2.0 | 字幕切分、翻译、配音 | 本地化基线 | — |
| [WyattBlue/auto-editor](https://github.com/WyattBlue/auto-editor/tree/16abfd30fa093a23d4af69f414e8a92d8ce5980e) | `16abfd30fa09` | Unlicense（公有领域） | 按静音与运动阈值自动剪切 | 规则剪辑基线（B1-cut） | 作为最终剪法 |
| [SamurAIGPT/AI-Youtube-Shorts-Generator](https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator/tree/4cfa5f00d65b4dca05bec92c67bfeb3af66cdfb3) | `4cfa5f00d65b` | MIT | 长视频自动拆短条 | 拆条基线 | — |
| [RayVentura/ShortGPT](https://github.com/RayVentura/ShortGPT/tree/3df4e0f7a422bf7386565d498bf4521a2544c614) | `3df4e0f7a422` | MIT | 短视频自动化框架 | 流水线参照 | — |
| [m-bain/whisperX](https://github.com/m-bain/whisperX/tree/8d8e43bf3698dd1df4b011c0f1a8dd1d468ae365) | `8d8e43bf3698` | BSD-2-Clause | 词级对齐转写 | 词级时间来源之一 | — |
| [modelscope/FunASR](https://github.com/modelscope/FunASR/tree/96700f5cc1b16d179f28d071c5f91370ae345335) | `96700f5cc1b1` | MIT（模型权重另有许可） | 中文语音识别 | 中文词稿来源之一 | — |

## G 剪辑元素分类与数据集（6）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [GX77/Edit3K](https://github.com/GX77/Edit3K/tree/3ca8e803de1ab4ea2b3141975ed75e9887f4c6ad) | `3ca8e803de1a` | MIT | 6 类剪辑组件：特效 888、动画 176、转场 204、滤镜 228、贴纸 1,000、文字 598，共 3,094 个、618,800 段渲染视频 | 组件大类划分与“组件与素材解耦”的表征思路 | 数据集商用（需另核数据许可） |
| [acherstyx/AutoTransition](https://github.com/acherstyx/AutoTransition/tree/ccdffddc74a310e26f096063edafd675f0a5f934) | `ccdffddc74a3` | 无 LICENSE 文件 | 按镜头与音乐推荐转场；数据来自公开剪辑模板，104 种转场；后续 V-Trans4Style 扩为 6k 视频、5 种制作风格 | 转场推荐的评测方式；按制作风格条件化 | — |
| [PardoAlejo/MovieCuts](https://github.com/PardoAlejo/MovieCuts/tree/f256b8df493c2b3b29f2e2a719f817b1ac64322c) | `f256b8df493c` | MIT | 173,967 段、10 种剪切类型：cut-on-action、cut-away、cross-cut、emphasis/deemphasis、match-cut、smash-cut、reaction-in/out、l-cut、j-cut、speaker-change | 剪切类型词表进入节奏刻面与评测标签 | — |
| [dawitmureja/AVE](https://github.com/dawitmureja/AVE/tree/f473861fe378e0e261c7a34006227878aa5453a0) | `f473861fe378` | 无 LICENSE 文件 | 196,176 个镜头、5,591 个场景，15 名专业剪辑师标注镜头大小、角度、类型、运动、主体、内外景、人数、声源 | 优质样本的镜头属性标注口径 | 数据分发 |
| [labazh/VEU-Bench](https://github.com/labazh/VEU-Bench/tree/79d3bccf1d17a839c8e23efe3e938be9663de34e) | `79d3bccf1d17` | 无 LICENSE 文件 | 10 个剪辑维度分帧内、镜内、镜间三层；识别、推理、评判三阶段 19 项任务；约 5 万问答 | 剪辑元素三层模型；评判类任务的出题方式 | 数据分发 |
| [AlibabaResearch/cut-craft-bench](https://github.com/AlibabaResearch/cut-craft-bench/tree/df2b35d63822d0832679fe675a274c33c51f7f75) | `df2b35d63822` | 无 LICENSE 文件 | CutCraft：多镜头音视频生成的剪辑意图评测；Mode A 专家模型计算、Mode B 工具支撑的 VLM 评判、Mode C 量表问答；含镜头对齐、转场语义、蒙太奇分类、事件保真技能 | 分层混合评测框架 | 数据分发 |

## H 质量与评测（4）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [Netflix/vmaf](https://github.com/Netflix/vmaf/tree/cf677baaa039723876fff8c2677164f25102e684) | `cf677baaa039` | BSD-2-Clause-Patent | 全参考画质 | 转码与渲染回归 | 风格好坏判断 |
| [VQAssessment/DOVER](https://github.com/VQAssessment/DOVER/tree/f1ddc96215bc7fbcf8f315c65d47905f339c3419) | `f1ddc96215bc` | S-Lab License 1.0（仅非商业） | UGC 视频质量，分审美与技术两个视角 | 研究阶段的无参考画质代理指标 | 商用流水线中的评分（需另选）；作为审美结论 |
| [Vchitect/VBench](https://github.com/Vchitect/VBench/tree/fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490) | `fd18b3d055cb` | Apache-2.0 | 生成视频评测；VBench-2.0 有人体保真、可控性、创造力、物理、常识 5 大类 18 个子维度 | 生成插入镜的质量代理 | 剪辑风格评价 |
| [TIGER-AI-Lab/VideoScore2](https://github.com/TIGER-AI-Lab/VideoScore2/tree/9e0fcbaeee0283b03efaaf8cd906f6381a808c75) | `9e0fcbaeee02` | MIT（模型权重另核） | 视觉质量、文本对齐、物理常识三维评分并给理由；VideoFeedback2 含 27,168 段带人工反馈视频 | 生成候选的预筛 | 最终验收 |

## I 摄影语言（2）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [Vchitect/ShotBench](https://github.com/Vchitect/ShotBench/tree/0f337a337a8cf2743e4bf4751d849fc0e8919f44) | `0f337a337a8c` | 无 LICENSE 文件 | 8 个摄影维度：景别、构图框定、机位角度、焦段、光线类型、光线条件、构图、运镜；3,049 张图、500 段视频、3,608 道题 | 优质样本与风格帧的标注维度 | 数据分发 |
| [sy77777en/CameraBench](https://github.com/sy77777en/CameraBench/tree/dd5740e44b925d7608b8ca109b51f3c49799f4ec) | `dd5740e44b92` | CC BY 4.0 | 约 3,000 段视频的相机运动分类（平移、旋转、变焦、环绕、稳定性、跟随），三种参照系 | 运镜词表与画面运动组件命名 | — |

## J 影调（2）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [AcademySoftwareFoundation/OpenColorIO](https://github.com/AcademySoftwareFoundation/OpenColorIO/tree/22dd9c4faa0d1b7cfb3d64d1a6e9cb454acc6cfd) | `22dd9c4faa0d` | BSD-3-Clause | 色彩管理，影述 Log 转换已使用 | 影调刻面的色彩空间基础 | — |
| [cyangraphics/clut](https://github.com/cyangraphics/clut/tree/af7b50d4caf6244fb6895a647f5b6a84efe7931a) | `af7b50d4caf6` | CC BY-SA 4.0（README 声明） | HaldCLUT 预设集合 | 影调参照 | 直接随包分发（相同方式共享） |

## K 开放评估补充：对齐、合规、声音、偏好与多语种（见 12 章）（17）

| 仓库 | 提交 | 许可 | 它提供什么 | 我们借鉴 | 不借鉴 |
|---|---|---|---|---|---|
| [QwenLM/Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR/tree/7c6daf77a2421100f5fb066495372c00129d39ff) | `7c6daf77a242` | Apache-2.0 | 52 种语言与方言识别；Qwen3-ForcedAligner-0.6B 支持 11 种语言、5 分钟内任意单位的时间戳 | 识别与对齐候选；影述已有逐窗实测（chinese-alignment.md） | 把结构合法的时间当作可剪边界 |
| [FireRedTeam/FireRedASR](https://github.com/FireRedTeam/FireRedASR/tree/834635e4cf277ed8ca92049fc375b17c3dc20748) | `834635e4cf27` | Apache-2.0 | 中文识别模型与流水线 | 识别对照 | — |
| [QwenLM/Qwen3-VL](https://github.com/QwenLM/Qwen3-VL/tree/96588727e44c78b25ba03ea03b8e12f7e64fd0da) | `96588727e44c` | Apache-2.0 | 视觉语言模型 | 风格指纹 L3 的候选标签（装饰度、设计语言族、字幕样式） | 不经人工确认直接定标签 |
| [google-research/frame-interpolation](https://github.com/google-research/frame-interpolation/tree/69f8708f08e62c2edf46a27616a4bfcf083e2076) | `69f8708f08e6` | Apache-2.0 | FILM 大位移帧插值 | 跳切的帧插值遮挡（≤ 6 帧、头部位移小） | 长间隔补帧 |
| [hzwer/ECCV2022-RIFE](https://github.com/hzwer/ECCV2022-RIFE/tree/5d8adbdd40e12c2c8f91930eff838aebe561c086) | `5d8adbdd40e1` | MIT | 实时帧插值 | 帧插值遮跳的快速路径 | — |
| [contentauth/c2pa-rs](https://github.com/contentauth/c2pa-rs/tree/bf30cc5ed8785165a42e17845ffe9eb2be4d4f4e) | `bf30cc5ed878` | Apache-2.0 | C2PA 内容凭证读写 | 出海版本的隐式标识与读回检查 | 宣称转码后仍可追溯 |
| [CodeGoat24/UnifiedReward](https://github.com/CodeGoat24/UnifiedReward/tree/ff6f520247a2d36e2aff7b2ba53a935afd437f66) | `ff6f520247a2` | MIT | 统一的多模态理解与生成奖励模型，支持成对排序与打分 | 自有风格奖励模型的底座 | — |
| [THUDM/VisionReward](https://github.com/THUDM/VisionReward/tree/511960d61a777b2008cd486a85a090ba96792a32) | `511960d61a77` | 代码 Apache-2.0；视频权重指向 CogVLM2 许可 | 分层、可解释的图像与视频偏好评分 | 可解释维度加权的做法 | 未核对权重许可前商用 |
| [westlake-repl/MicroLens](https://github.com/westlake-repl/MicroLens/tree/0fc876066987fb3b920df2765cfbac2763c515eb) | `0fc876066987` | 无 LICENSE 文件 | 百万级短视频推荐数据集 | 互动预测的研究参照 | 用于训练 |
| [hkchengrex/MMAudio](https://github.com/hkchengrex/MMAudio/tree/974010a026c731054592d8f777218bd9d85a6c24) | `974010a026c7` | 代码 MIT；权重 CC-BY-NC 4.0 | 视频到音频生成 | 拟音效果参照 | 进入商用链路 |
| [Tencent-Hunyuan/HunyuanVideo-Foley](https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley/tree/df7b005b5023df2a9b73e1d66dd51d452799884e) | `df7b005b5023` | 腾讯混元社区许可：不适用于欧盟、英国、韩国；月活超 1 亿须另行申请 | 视频拟音生成 | 国内版本拟音候选，须法务确认 | 海外版本 |
| [FunAudioLLM/ThinkSound](https://github.com/FunAudioLLM/ThinkSound/tree/4e2cfd57efaaf40c90460d8111b6a3c1e7dfb2f0) | `4e2cfd57efaa` | 无 LICENSE 文件；README 写明不允许商用 | 链式推理的视频配音效 | — | 使用 |
| [ace-step/ACE-Step](https://github.com/ace-step/ACE-Step/tree/1bee4c9f5b43e30995f8d4d33b3919197ce1bd68) | `1bee4c9f5b43` | Apache-2.0 | 音乐生成基础模型 | 纯音乐床 | 中文歌词（罗马化处理，效果未证实） |
| [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice/tree/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc) | `074ca6dc9e80` | Apache-2.0 | 多语种语音合成 | 多语种配音 | — |
| [index-tts/index-tts](https://github.com/index-tts/index-tts/tree/d9e41aac89fd00b3d71497fddb287b7f24613712) | `d9e41aac89fd` | bilibili 模型使用协议：月活超 1 亿或年营收超 10 亿元须另行授权；不得用于改进其他模型 | 可控情绪与时长的语音合成 | 配音候选，须评估协议 | 未评估前商用 |
| [bytedance/LatentSync](https://github.com/bytedance/LatentSync/tree/a229c3948406bc2cf6eaf4873e662e70c6a04746) | `a229c3948406` | Apache-2.0 | 扩散式口型同步 | 译配版口型（质量优先） | — |
| [TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk/tree/2536eaf06b85f775d8e04b7fd81bf6699155a58d) | `2536eaf06b85` | 代码 MIT；依赖模型各自许可 | 实时口型同步 | 译配版口型（速度优先） | 未核对依赖许可前商用 |

