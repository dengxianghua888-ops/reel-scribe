# 动效组件与渲染引擎目录

catalog-draft：结构化设计条目，未渲染、未评测；数量不代表已验证风格。

## 渲染引擎

| ID | 引擎 | 最适合 | 强项 | 局限 | 确定性 | 许可提示 |
|---|---|---|---|---|---|---|
| `ass` | ASS/libass 字幕引擎 | 字幕、卡拉OK、逐词强调、简单文字动画 | 最快，与 caption-burn 同链，确定性高 | 图形与复杂排版弱；中文排版需自控断行 | 确定 | libass ISC |
| `ffmpeg` | FFmpeg 滤镜图 | 变换、裁切推近、调色、xfade 转场、色键、马赛克、静态叠加 | 无额外运行时，速度最快 | 动画曲线与排版能力有限 | 确定 | LGPL/GPL 按构建 |
| `html` | HTML/CSS/JS 逐帧渲染 | 信息卡、数据图、中文排版、UI 与社媒卡片、文字动画 | 排版与设计 token 最强，可用 GSAP/WAAPI/anime.js，可 seek | 需固定版本无头浏览器；渲染中速 | 固定浏览器与种子后确定 | Hyperframes Apache-2.0 可作参照 |
| `react` | React 组件渲染（Remotion 类） | 复杂状态组件、模板生态 | 组件化与生态成熟 | Remotion 公司规模超限需商业授权 | 确定 | Remotion 源码可见许可 |
| `canvas` | 程序化矢量动画（Motion Canvas/Revideo） | 图解、流程、代码动画、教学示意 | 生成器式时间控制，适合讲解 | 不擅长照片级与实拍合成 | 确定 | MIT |
| `lottie` | Lottie 渲染（rlottie/lotio/lottie-web） | 设计师 AE 资产、图标与角色小动画、手写笔顺 | 复用设计资产，体积小 | 可编辑属性有限（文本层、颜色、时间）；表达式支持不全 | 确定 | lottie-web MIT，rlottie MIT |
| `glsl` | WebGL/GLSL 着色器 | 转场、风格化、光效、背景 | 效果上限高，gl-transitions 有 387 个现成转场 | 需 GPU 或软件 GL；参数语义需自建 | 确定 | gl-transitions MIT |
| `three` | Three.js/WebGPU 3D | 3D 立体字、产品转台、空间卡片、2.5D 视差 | 真实空间感 | 建模与光照成本高 | 固定种子后确定 | MIT |
| `manim` | Manim | 公式推导、数学与物理示意 | 数学排版与变换最佳 | 风格单一，需定制主题 | 确定 | MIT |
| `blender` | Blender Python | 高品质 3D、实拍合成、物理模拟 | 上限最高 | 最慢，资产与渲染农场成本 | 确定（固定版本） | GPL（输出不受限） |
| `vision` | 视觉分析模型 | 主体遮罩、人像抠像、跟踪、切点与主体框 | 为合成与跟踪提供数据 | 本身不画图；需 GPU 或慢速 CPU；边缘与闪烁需检查 | 模型版本固定后可复现 | SAM2 Apache-2.0；RVM GPL-3.0；CoTracker CC BY-NC 与 MatAnyone S-Lab 仅限非商业，商用需另选 |
| `stylize` | 风格迁移与转绘 | 真人转手绘、素描、绘本化窗口 | 能做实拍无法得到的质感 | 跨帧稳定性与身份保持是难点 | 依模型 | EbSynth 公有领域；扩散模型按模型许可 |
| `host` | 宿主原生（剪辑 Agent 时间线） | 可编辑字幕、MG 实例、关键帧、变速、音量包络 | 可编辑性最好，用户可直接改 | 效果受宿主组件库限制 | 宿主决定 | — |
| `gen` | 生成模型 | 补镜、产品演示、背景与素材生成 | 得到实拍没有的画面 | 片内修改需重生成；费用；事实不能作证据 | 不确定 | 按服务条款 |

## 文字动画（14）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `txt-fade-rise` | 渐显上浮 | `html` | `ass` | text、color_role、duration | 4 |
| `txt-per-word-rise` | 逐词升起 | `html` | `ass` | text、stagger_ms | 1 |
| `txt-typewriter` | 打字机 | `ass` | `html` | text、cps、cursor | 2 |
| `txt-scramble-decode` | 乱码解码 | `html` | — | text、charset、duration | 2 |
| `txt-slam` | 重锤砸入 | `html` | `ass` | text、scale_from、shake | 17 |
| `txt-blur-in` | 模糊聚焦 | `html` | `ffmpeg` | text、blur_px | 1 |
| `txt-mask-reveal` | 遮罩揭示 | `html` | — | text、direction | 2 |
| `txt-stroke-draw` | 描边书写 | `html` | `lottie` | text、stroke_width | 1 |
| `txt-split-flap` | 翻牌显示 | `html` | — | text、flip_ms | 2 |
| `txt-variable-weight` | 字重呼吸 | `html` | — | text、weight_range | 1 |
| `txt-gloss-sweep` | 光泽扫过 | `html` | `glsl` | text、angle | 4 |
| `txt-handwrite` | 手写笔顺 | `lottie` | `html` | text、stroke_order | 5 |
| `txt-calligraphy-title` | 书法题字 | `lottie` | `html` | text、brush_asset | 3 |
| `txt-3d-extrude` | 立体字 | `three` | `blender` | text、depth、material | 1 |

## 字幕效果（10）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `cap-karaoke-fill` | 逐词填色 | `ass` | `html` | fill_color_role | 2 |
| `cap-pill-highlight` | 胶囊底高亮 | `html` | `ass` | pill_color_role、radius | 3 |
| `cap-word-pop` | 逐词弹出 | `ass` | `html` | scale、overshoot | 28 |
| `cap-keyword-recolor` | 关键词变色 | `ass` | `html` | keyword_ids、color_role | 72 |
| `cap-emoji-pop` | 表情点缀 | `html` | `lottie` | emoji、density | 1 |
| `cap-behind-subject` | 文字穿人 | `vision` | `html` | word_ids、coverage_target | 1 |
| `cap-camera-follow-3d` | 3D 跟随字幕 | `vision` | `three` | anchor、depth | 1 |
| `cap-bilingual-stack` | 双语上下 | `ass` | `html` | primary_lang、secondary_scale | 5 |
| `cap-speaker-color` | 说话人分色 | `ass` | — | speaker_color_map | 9 |
| `cap-danmaku` | 弹幕滚动 | `ass` | `html` | lanes、speed | 2 |

## 强调与标注（10）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `anno-marker-highlight` | 荧光划线 | `html` | `ass` | target_word_ids、color_role | 4 |
| `anno-underline-draw` | 下划线描出 | `html` | — | target、thickness | 2 |
| `anno-circle-callout` | 手绘圈注 | `lottie` | `html` | target_rect | 7 |
| `anno-arrow-point` | 箭头指示 | `html` | `lottie` | from、to、curve | 8 |
| `anno-box-label` | 框选标签 | `html` | — | rect、label | 17 |
| `anno-strike-replace` | 划掉改写 | `html` | — | old_text、new_text | 5 |
| `anno-magnifier` | 局部放大镜 | `ffmpeg` | `html` | src_rect、zoom | 7 |
| `anno-spotlight` | 聚光压暗 | `ffmpeg` | `html` | rect、dim | 1 |
| `anno-red-pen` | 红笔批改 | `lottie` | `html` | target、mark_type | 4 |
| `anno-source-label` | 来源标注 | `html` | `ass` | source_text | 15 |

## 数据与数值（13）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `data-count-up` | 数字滚动 | `html` | — | from、to、unit、format | 11 |
| `data-number-impact` | 巨型数字 | `html` | — | value、unit、label | 9 |
| `data-bar-chart` | 柱状图 | `html` | `canvas` | series、unit、highlight | 6 |
| `data-line-graph` | 折线图 | `html` | `canvas` | series、unit、annotations | 5 |
| `data-donut` | 环形占比 | `html` | — | parts、unit | 2 |
| `data-bar-race` | 排名竞赛 | `html` | — | frames、unit | 2 |
| `data-progress-ring` | 进度环 | `html` | — | value、max | 5 |
| `data-spec-table` | 规格表逐行点亮 | `html` | `host` | rows、active_row、side | 5 |
| `data-compare-split` | 左右对比 | `html` | `ffmpeg` | left、right、axis | 7 |
| `data-star-rating` | 星级评分 | `html` | — | score、max | 3 |
| `data-timeline` | 时间轴 | `html` | `canvas` | events、active | 12 |
| `data-map-route` | 地图路线 | `html` | `canvas` | points、route、active | 8 |
| `data-price-tag` | 价格条件标签 | `html` | `host` | price、condition、valid_until | 4 |

## 信息卡与版式（14）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `card-lower-third` | 姓名条 | `html` | `host` | name、title、side | 27 |
| `card-chapter` | 章节页 | `html` | `host` | index、title | 20 |
| `card-title` | 片头标题 | `html` | `lottie` | title、subtitle | 14 |
| `card-quote` | 引语卡 | `html` | — | text、attribution | 15 |
| `card-checklist` | 清单勾选 | `html` | — | items、checked | 19 |
| `card-step` | 步骤指示 | `html` | `ass` | step、total、label | 12 |
| `card-testimonial` | 用户评价卡 | `html` | — | text、author、rating | 1 |
| `card-social-post` | 社媒帖与评论卡 | `html` | — | author、text、metrics | 3 |
| `card-chat-thread` | 聊天气泡 | `html` | — | messages | 1 |
| `card-notification` | 通知弹出 | `html` | — | app、text | 1 |
| `card-cta-end` | 片尾引导 | `html` | `host` | text、handle | 6 |
| `card-logo-sting` | 标志落版 | `lottie` | `html` | logo_asset | 7 |
| `card-question` | 问题卡 | `html` | — | question | 6 |
| `card-ticker` | 新闻滚动条 | `html` | `ass` | items、speed | 2 |

## 画面运动（9）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `cam-punch-in` | 推近强调 | `ffmpeg` | `host` | scale、center、ease | 10 |
| `cam-ken-burns` | 静图运镜 | `ffmpeg` | — | from_rect、to_rect | 9 |
| `cam-reframe-follow` | 主体跟随重构图 | `vision` | `ffmpeg` | subject、aspect | 2 |
| `cam-speed-ramp` | 速度曲线 | `host` | `ffmpeg` | curve | 6 |
| `cam-freeze-frame` | 定格 | `ffmpeg` | — | frame、hold_ms | 9 |
| `cam-shake` | 震动 | `ffmpeg` | `html` | amplitude、decay | 2 |
| `cam-rack-focus` | 虚实转换 | `ffmpeg` | `glsl` | from、to | 1 |
| `cam-whip-pan` | 甩镜 | `glsl` | `ffmpeg` | direction | 1 |
| `cam-parallax-25d` | 照片 2.5D 视差 | `vision` | `three` | depth_scale | 2 |

## 转场（12）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `tr-dissolve` | 叠化 | `ffmpeg` | — | duration | 2 |
| `tr-dip-color` | 闪白闪黑 | `ffmpeg` | — | color、duration | 5 |
| `tr-wipe` | 方向擦除 | `ffmpeg` | `glsl` | direction、softness | 4 |
| `tr-push-slide` | 推移 | `ffmpeg` | `glsl` | direction | 1 |
| `tr-zoom-through` | 穿越推进 | `glsl` | `html` | center | 3 |
| `tr-glitch` | 故障转场 | `glsl` | — | intensity | 1 |
| `tr-light-leak` | 漏光转场 | `glsl` | `ffmpeg` | leak_asset | 3 |
| `tr-ink-bleed` | 墨晕转场 | `glsl` | — | spread | 5 |
| `tr-paper-tear` | 撕纸转场 | `glsl` | `html` | edge_asset | 3 |
| `tr-shape-iris` | 形状遮罩开合 | `glsl` | `ffmpeg` | shape、center | 1 |
| `tr-film-burn` | 胶片烧灼 | `glsl` | — | intensity | 1 |
| `tr-match-assist` | 匹配剪辑辅助 | `vision` | — | shape_anchor | 2 |

## 合成（8）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `comp-pip` | 画中画 | `ffmpeg` | `host` | rect、border | 1 |
| `comp-split-screen` | 分屏 | `ffmpeg` | `host` | layout | 17 |
| `comp-device-frame` | 设备样机 | `html` | — | device、screen_src | 2 |
| `comp-chroma-key` | 色键抠像 | `ffmpeg` | — | key_color、tolerance | 1 |
| `comp-subject-cutout` | 人物抠像 | `vision` | — | subject、feather | 1 |
| `comp-bg-replace` | 背景虚化或替换 | `vision` | `ffmpeg` | mode、asset | 1 |
| `comp-collage-layer` | 拼贴分层 | `html` | `vision` | layers | 5 |
| `comp-mono-keep-subject` | 黑白留人像色 | `vision` | `ffmpeg` | subject | 1 |

## 跟踪附着（3）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `trk-label-follow` | 跟踪标签 | `vision` | `html` | target、label | 2 |
| `trk-mosaic` | 跟踪打码 | `vision` | `ffmpeg` | target、mode | 1 |
| `trk-object-outline` | 实物线框 | `vision` | `html` | target、style | 1 |

## 风格化（7）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `sty-film-grain` | 胶片颗粒与光晕 | `ffmpeg` | — | grain、halation、vignette | 3 |
| `sty-vhs` | 录像带 | `glsl` | `ffmpeg` | intensity | 1 |
| `sty-halftone` | 网点印刷 | `glsl` | — | dot_size | 1 |
| `sty-duotone` | 双色调 | `ffmpeg` | `glsl` | colors | 1 |
| `sty-paper-texture` | 纸纹叠加 | `ffmpeg` | `html` | paper_asset、opacity | 1 |
| `sty-handpaint-window` | 转绘窗口 | `stylize` | — | range、reference | 1 |
| `sty-line-sketch` | 线稿化 | `glsl` | `stylize` | line_weight | 1 |

## 光效与粒子（5）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `fx-light-leak` | 漏光叠加 | `ffmpeg` | `glsl` | asset、opacity | 1 |
| `fx-glow-bloom` | 辉光 | `glsl` | `ffmpeg` | threshold、radius | 1 |
| `fx-confetti` | 彩纸粒子 | `html` | `glsl` | density、palette | 3 |
| `fx-snow-rain` | 雨雪 | `glsl` | `html` | density | 1 |
| `fx-sparkle` | 闪光点缀 | `html` | — | target | 1 |

## 背景与氛围（4）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `bg-gradient-mesh` | 渐变网格 | `html` | `glsl` | palette | 1 |
| `bg-aurora` | 极光流动 | `glsl` | — | palette、speed | 1 |
| `bg-grid-paper` | 方格纸 | `html` | — | grid、color_role | 1 |
| `bg-noise-texture` | 噪点质感 | `glsl` | `ffmpeg` | scale | 1 |

## 屏幕与软件（6）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `scr-cursor-zoom` | 光标跟随放大 | `ffmpeg` | `html` | focus_rect、zoom | 7 |
| `scr-click-ripple` | 点击涟漪 | `html` | — | point | 2 |
| `scr-code-typing` | 代码打字 | `html` | `canvas` | code、language | 2 |
| `scr-code-diff` | 代码差异 | `html` | `canvas` | before、after | 1 |
| `scr-browser-frame` | 浏览器框 | `html` | — | url、screen_src | 1 |
| `scr-keystroke` | 按键提示 | `html` | `ass` | keys | 4 |

## 贴纸与表情（3）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `stk-emoji-pop` | 表情弹出 | `html` | `lottie` | emoji | 4 |
| `stk-sticker-bounce` | 贴纸弹跳 | `lottie` | `html` | asset | 5 |
| `stk-reaction-burst` | 反应特效字 | `html` | — | text、palette | 9 |

## 声画联动（3）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `av-beat-pulse` | 节拍脉冲 | `html` | `glsl` | beats、intensity | 6 |
| `av-waveform` | 声波 | `html` | `canvas` | audio_ref、style | 1 |
| `av-beat-freeze` | 卡点定格 | `ffmpeg` | `host` | beats | 3 |

## 图解与公式（5）

| ID | 组件 | 首选引擎 | 备选引擎 | 可编辑属性 | 被引用次数 |
|---|---|---|---|---|---|
| `dia-flowchart` | 流程图 | `canvas` | `html` | nodes、edges、active | 7 |
| `dia-cause-map` | 因果图 | `canvas` | `html` | nodes、edges | 4 |
| `dia-whiteboard` | 白板手绘 | `lottie` | `html` | strokes | 3 |
| `dia-formula` | 公式推导 | `manim` | `html` | latex_steps | 4 |
| `dia-product-turntable` | 产品转台 | `three` | `blender` | model、turns | 1 |

