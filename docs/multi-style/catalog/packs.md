# 场景 × 风格包目录

catalog-draft：结构化设计条目，未渲染、未评测；数量不代表已验证风格。

共 42 个场景、264 个风格包（皮肤包 244、机制包 20），引用 218 张现有方法卡。生成方式：`python3 docs/multi-style/tools/build_catalog.py`。

## 真人口播与知识表达

### S01 知识科普口播

工作流 `raven-speech-edit` · 素材起点：单人口播原片 · 关键信号：步骤、概念关系、误区、数值

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `kn-whiteboard` 白板图解 | 递进教学（`speech/stepwise-teaching`） | 白板马克笔 | 短语分组极简 | 清透提亮 | Lo-fi 底声 | 白板手绘、箭头指示、步骤指示 | 笔画顺序跟着解释走 | 皮肤 |
| `kn-myth-redpen` 误区红笔 | 误区纠正（`speech/myth-correction`） | 红笔批改 | 关键词变色 | 中性准确 | 极简提示音 | 划掉改写、红笔批改、来源标注 | 先划掉旧说法，再写正确边界 | 皮肤 |
| `kn-outline-build` 随讲累积提纲 | 随讲累积提纲（`speech/progressive-outline`） | 极简留白 | 极简细字 | 清透提亮 | 只留人声 | 清单勾选、渐显上浮 | 旧项不消失，新项随原话加入 | 皮肤 |
| `kn-question-card` 问题驱动 | 问题驱动答疑（`speech/question-answer`） | 瑞士网格 | 关键词加粗放大 | 中性准确 | 极简提示音 | 问题卡、遮罩揭示 | 每段以一张问题卡开场 | 皮肤 |
| `kn-data-explainer` 数据讲解 | 证据解释（`speech/evidence-led`） | 浅色科技看板 | 关键词变色 | 清透提亮 | 极简提示音 | 柱状图、数字滚动、来源标注 | 每个数都带来源角标 | 皮肤 |
| `kn-analogy-collage` 拼贴类比 | 轻幽默讲解（`speech/humorous-explanation`） | 撕纸拼贴 | 关键词加粗放大 | 暖调生活 | 观点重音 | 拼贴分层、贴纸弹跳、撕纸转场、纸纹叠加 | 比喻用拼贴画出来再回到原题 | 皮肤 |
| `kn-expert-deep` 专业深讲 | 专业深讲（`speech/expert-deep-dive`） | 蓝图线框 | 短语分组极简 | 冷调科技 | 只留人声 | 流程图、框选标签、章节页 | 线框图跟着推理一层层展开 | 皮肤 |
| `kn-formula` 公式推导 | 递进教学（`speech/stepwise-teaching`） | 现代主义几何 | 极简细字 | 中性准确 | 只留人声 | 公式推导、下划线描出、方格纸 | 每步推导停在可读处 | 皮肤 |

### S02 观点评论

工作流 `raven-speech-edit` · 素材起点：单人口播原片 · 关键信号：主张、转折、反例、引语

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `op-manifesto` 宣言大字 | 紧凑观点（`speech/crisp-argument`） | 黄白宣言 | 组件承担时让位 | 高对比黑白 | 观点重音 | 引语卡、重锤砸入 | 一句话占满一拍 | 皮肤 |
| `op-counterpoint` 观点与反证 | 观点与反证（`speech/counterpoint-dialogue`） | 新闻编辑部 | 衬线引语 | 中性准确 | 只留人声 | 分屏、引语卡、来源标注 | 正反并排，反例单独成卡 | 皮肤 |
| `op-word-slam` 逐词冲击 | 紧凑观点（`speech/crisp-argument`） | 黑黄重字 | 大字逐词冲击 | 中性准确 | 观点重音 | 推近强调 | 每屏 1–3 个词，主张词最大 | 皮肤 |
| `op-balanced` 条件式对比 | 条件式对比（`speech/balanced-comparison`） | 瑞士网格 | 关键词变色 | 中性准确 | 极简提示音 | 左右对比、清单勾选 | 在什么条件下选哪个，用表格落地 | 皮肤 |
| `op-behind-subject` 文字穿人 | 转折约束显影（`speech/constraint-pivot`） | 酸绿花字 | 文字穿人 | 胶片青绿 | 观点重音 | 人物抠像、重锤砸入 | 大字从人物身后穿过 | 机制 |
| `op-editorial-column` 专栏评论 | 问题与应对专题（`speech/issue-context`） | 财经报刊 | 衬线引语 | 低饱和高级灰 | 资讯底乐 | 章节页、引语卡、来源标注 | 每个论点一页专栏版式 | 皮肤 |
| `op-meme-commentary` 热梗评论 | 轻幽默讲解（`speech/humorous-explanation`） | 爆梗红字 | 综艺花字 | 录像带复古 | 综艺音效 | 反应特效字、推近强调、社媒帖与评论卡 | 先引原帖再给反应 | 皮肤 |

### S03 数码家电测评

工作流 `raven-speech-edit` · 素材起点：口播原片＋产品 B-roll · 关键信号：规格对、测量读数、比较、缺点

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `rv-spec-redline` 红黑参数看板 | 证据解释（`speech/evidence-led`） | 黑底红行 | 关键词变色 | 冷调科技 | 极简提示音 | 规格表逐行点亮、巨型数字 | 只点亮正在讲的那一行 | 皮肤 |
| `rv-light-board` 浅色对比看板 | 条件明确的比较（`commerce/honest-comparison`） | 浅色科技看板 | 短语分组极简 | 商品真色 | 极简提示音 | 左右对比、柱状图、星级评分 | 同条件对比，差值用柱子说话 | 皮肤 |
| `rv-wireframe` 线框实物 | 功能落到动作（`commerce/feature-to-action`） | 蓝图线框 | 关键词变色 | 冷调科技 | 极简提示音 | 实物线框、跟踪标签、线稿化 | 实物转线框并跟着标注 | 机制 |
| `rv-long-term-diary` 长期使用日记 | 真实使用日记（`commerce/real-use-diary`） | 生活画报 | 手写体整句 | 暖调生活 | 原声吉他 | 时间轴、章节页 | 按使用天数推进 | 皮肤 |
| `rv-limitation-first` 先说缺点 | 限制先说清（`commerce/limitation-first`） | 红笔批改 | 关键词变色 | 中性准确 | 只留人声 | 红笔批改、清单勾选 | 开头先划掉不适合的人 | 皮肤 |
| `rv-unbox-setup` 开箱到上手 | 真实上手门槛（`commerce/setup-reality`） | 瑞士网格 | 短语分组极简 | 商品真色 | 拟音前置 | 步骤指示、局部放大镜 | 每个上手步骤都有完成画面 | 皮肤 |
| `rv-measurement` 测量讲清 | 测量说清楚（`commerce/measurement-explained`） | 黑绿终端 | 关键词加粗放大 | 冷调科技 | 极简提示音 | 数字滚动、折线图、来源标注 | 测量条件与读数同屏 | 皮肤 |

### S04 教学讲解

工作流 `raven-speech-edit` · 素材起点：讲课原片 · 关键信号：步骤、例题、常见错误、检验方法

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `te-stepwise` 递进教学 | 递进教学（`speech/stepwise-teaching`） | 浅色科技看板 | 短语分组极简 | 清透提亮 | 只留人声 | 步骤指示、箭头指示 | 每步只讲一件事并给检验方法 | 皮肤 |
| `te-worked-example` 例题拆解 | 例题带学（`course-meeting/worked-example`） | 纸感荧光 | 关键词变色 | 清透提亮 | 只留人声 | 荧光划线、公式推导 | 每步高亮被用到的条件 | 皮肤 |
| `te-misconception` 误区修复 | 误区纠偏（`course-meeting/misconception-repair`） | 红笔批改 | 关键词加粗放大 | 中性准确 | 极简提示音 | 划掉改写 | 学生常错的那一步单独慢讲 | 皮肤 |
| `te-concept-ladder` 概念阶梯 | 概念阶梯（`course-meeting/concept-ladder`） | 现代主义几何 | 短语分组极简 | 中性准确 | Lo-fi 底声 | 流程图、章节页 | 每级概念在阶梯图上点亮 | 皮肤 |
| `te-practice-pause` 练习暂停 | 练习停顿（`course-meeting/practice-pause`） | 牛皮纸便签 | 手写体整句 | 暖调生活 | Lo-fi 底声 | 问题卡、进度环 | 讲完给倒计时让观众先想 | 皮肤 |
| `te-retrieval-review` 回顾速记 | 速查复习（`course-meeting/retrieval-review`） | 瑞士网格 | 关键词加粗放大 | 清透提亮 | 极简提示音 | 清单勾选、翻牌显示 | 结尾一屏要点逐条翻牌 | 皮肤 |

### S05 个人经历与情感口播

工作流 `raven-speech-edit` · 素材起点：口播原片＋旧照片或 B-roll · 关键信号：故事节拍、情绪峰、停顿

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ps-reflective` 克制独白 | 克制独白（`speech/reflective-monologue`） | 极简留白 | 电影字幕 | 胶片暖褐 | 纪实房间底噪 | 模糊聚焦 | 整片只有一次音乐进入 | 皮肤 |
| `ps-letter` 信件体 | 个人经历（`speech/personal-story`） | 老照片相册 | 手写体整句 | 档案褪色 | 原声吉他 | 静图运镜、手写笔顺 | 旧照片配手写日期 | 皮肤 |
| `ps-case-rebuild` 案例复盘 | 案例复盘（`speech/case-reconstruction`） | 剪报档案 | 短语分组极简 | 纪实自然 | 只留人声 | 时间轴、手绘圈注 | 时间线上圈出那次关键选择 | 皮肤 |
| `ps-companion` 自然陪伴 | 自然陪伴（`speech/conversational-company`） | 纸感荧光 | 手写体整句 | 柔肤人像 | Lo-fi 底声 | 荧光划线 | 只划一处最想让你记住的话 | 皮肤 |
| `ps-mono-portrait` 黑白人物 | 个人经历（`speech/personal-story`） | 黑白人物志 | 衬线引语 | 黑白留人像色 | 环境声主导 | 章节页、黑白留人像色 | 黑白中只有人保留原色 | 机制 |
| `ps-handpaint-memory` 回忆转绘 | 个人经历（`speech/personal-story`） | 生活画报 | 极简细字 | 绘本柔彩 | 原声吉他 | 转绘窗口、分屏 | 讲到回忆时实拍转为手绘 | 机制 |

### S06 资讯快讯播报

工作流 `raven-speech-edit` · 素材起点：播报原片＋来源材料 · 关键信号：事实条目、来源、更新、地点

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `nb-newsroom` 新闻条带 | 事实简报（`documentary/fact-brief`） | 新闻编辑部 | 新闻下三分之一 | 中性准确 | 资讯底乐 | 新闻滚动条、来源标注、姓名条 | 每条一句标题加来源 | 皮肤 |
| `nb-daily-digest` 每日要点 | 进展快照（`documentary/ongoing-snapshot`） | 瑞士网格 | 关键词加粗放大 | 清透提亮 | 资讯底乐 | 翻牌显示、清单勾选、推移 | 开头翻牌列出今日三件事 | 皮肤 |
| `nb-change-since` 更新对比 | 更新差异（`documentary/change-since-update`） | 浅色科技看板 | 关键词变色 | 中性准确 | 极简提示音 | 左右对比、划掉改写 | 上次的数字被新数字划掉 | 皮肤 |
| `nb-map-dispatch` 地图快讯 | 现场观察札记（`documentary/field-dispatch`） | 蓝图线框 | 纪录片说明字 | 纪实自然 | 资讯底乐 | 地图路线、姓名条 | 每条先在地图上落点 | 皮肤 |
| `nb-known-unknown` 已知与未知 | 已知与未决（`documentary/known-unknown`） | 财经报刊 | 短语分组极简 | 低饱和高级灰 | 只留人声 | 清单勾选、框选标签 | 已确认与待确认分两栏 | 皮肤 |
| `nb-vertical-flash` 竖屏快讯 | 后续影响（`documentary/consequences`） | 深蓝冲击 | 大字逐词冲击 | 清透提亮 | 观点重音 | 巨型数字、片头标题 | 一个数字定开头 | 皮肤 |

### S07 财经商业分析

工作流 `raven-speech-edit` · 素材起点：口播原片＋数据 · 关键信号：数值、趋势、因果、引语

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `fi-journal` 财经报刊 | 证据解释（`speech/evidence-led`） | 财经报刊 | 衬线引语 | 低饱和高级灰 | 资讯底乐 | 折线图、引语卡、来源标注 | 数据页与引语页交替 | 皮肤 |
| `fi-impact-numbers` 大数冲击 | 紧凑观点（`speech/crisp-argument`） | 深蓝冲击 | 组件承担时让位 | 冷调科技 | 观点重音 | 巨型数字、排名竞赛 | 关键数字占满一拍 | 皮肤 |
| `fi-cause-chain` 因果链条 | 专业深讲（`speech/expert-deep-dive`） | 蓝图线框 | 短语分组极简 | 冷调科技 | Lo-fi 底声 | 因果图、数字滚动 | 一张因果图贯穿全片 | 皮肤 |
| `fi-archive-collage` 档案拼贴讲解 | 机制解释（`documentary/mechanism-explainer`） | 剪报档案 | 关键词变色 | 档案褪色 | 资讯底乐 | 拼贴分层、静图运镜、撕纸转场 | 史料剪报拼出来龙去脉 | 皮肤 |
| `fi-executive-brief` 决策简报 | 决策简报（`speech/executive-brief`） | 蓝色专业 | 短语分组极简 | 中性准确 | 只留人声 | 清单勾选、环形占比 | 结论、依据、下一步三页 | 皮肤 |
| `fi-chart-race` 排名竞赛 | 条件式对比（`speech/balanced-comparison`） | 深色流光 | 关键词加粗放大 | 冷调科技 | 节拍驱动 | 排名竞赛、时间轴 | 排名变化跟着讲述推进 | 皮肤 |

### S08 企业发言与正式讲话

工作流 `raven-speech-edit` · 素材起点：讲话录像＋原稿 · 关键信号：承诺、行动主体、议题、限定

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ex-complete-record` 完整留档 | 完整留档（`speech/complete-record`） | 蓝色专业 | 短语分组极简 | 中性准确 | 纪实房间底噪 | 姓名条 | 不剪掉任何限定与承诺 | 皮肤 |
| `ex-actor-action` 行动清单 | 行动主体清单（`speech/actor-action`） | 瑞士网格 | 关键词变色 | 中性准确 | 只留人声 | 清单勾选、姓名条 | 谁要做什么逐条列出 | 皮肤 |
| `ex-issue-brief` 议题专题 | 问题与应对专题（`speech/issue-context`） | 新闻编辑部 | 衬线引语 | 低饱和高级灰 | 资讯底乐 | 章节页、引语卡 | 每个议题一页原话 | 皮肤 |
| `ex-premium-keynote` 发布会高端 | 紧凑观点（`speech/crisp-argument`） | 黑金高端 | 极简细字 | 黑金质感 | 商务明亮 | 片头标题、巨型数字、标志落版 | 黑场中一个数字亮起 | 皮肤 |
| `ex-warm-allhands` 内部温暖版 | 自然陪伴（`speech/conversational-company`） | 暖橙几何 | 短语分组极简 | 暖调生活 | 原声吉他 | 姓名条、彩纸粒子 | 彩纸只给真正的里程碑 | 皮肤 |
| `ex-bilingual-global` 双语对外 | 归属清晰论证（`localization/attributed-argument`） | 蓝色专业 | 双语上下 | 中性准确 | 纪实房间底噪 | 姓名条 | 术语首现给原文 | 皮肤 |

## 对话与多人

### S09 人物访谈

工作流 `raven-interview-multicam` · 素材起点：多机位访谈 · 关键信号：问答关系、说话人、金句、章节

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `iv-portrait` 人物肖像 | 人物内省（`interview/reflective-portrait`） | 黑白人物志 | 电影字幕 | 高对比黑白 | 纪实房间底噪 | 姓名条、章节页 | 每章前一张静止人物页 | 皮肤 |
| `iv-oral-history` 口述历史 | 口述历史（`interview/oral-history`） | 老照片相册 | 纪录片说明字 | 档案褪色 | 纪实房间底噪 | 静图运镜、时间轴 | 原话与老照片交替 | 皮肤 |
| `iv-idea-duel` 观点交锋 | 观点交锋（`interview/idea-duel`） | 深蓝冲击 | 多人分色 | 中性准确 | 观点重音 | 分屏、引语卡 | 分屏对峙，金句单独上卡 | 皮肤 |
| `iv-practitioner` 实践案例 | 实战案例复盘（`interview/practitioner-case`） | 浅色科技看板 | 短语分组极简 | 清透提亮 | Lo-fi 底声 | 步骤指示、框选标签 | 问题、做法、结果三段 | 皮肤 |
| `iv-short-answers` 短答卡 | 单问题短答（`interview/short-answer-card`） | 瑞士网格 | 关键词加粗放大 | 清透提亮 | 极简提示音 | 问题卡、遮罩揭示 | 一个问题一张卡一个回答 | 皮肤 |
| `iv-place` 场所沉浸 | 在场访谈（`interview/place-immersive`） | 生活画报 | 极简细字 | 纪实自然 | 环境声主导 | 姓名条 | 受访者的空间先于受访者出现 | 皮肤 |
| `iv-technical` 技术深谈 | 专业深谈（`interview/technical-deep-dive`） | 蓝图线框 | 关键词变色 | 冷调科技 | 只留人声 | 流程图、框选标签 | 关键概念随对话画成图 | 皮肤 |

### S10 视频播客与圆桌

工作流 `raven-interview-multicam` · 素材起点：多机位或单机位多人录制 · 关键信号：回应关系、分歧、笑点、金句

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `pc-roundtable-map` 圆桌地图 | 圆桌观点地图（`interview/roundtable-map`） | 暖橙几何 | 多人分色 | 暖调生活 | 纪实房间底噪 | 姓名条、流程图 | 谁回应了谁用连线标出 | 皮肤 |
| `pc-audiogram` 声波卡片 | 单问题短答（`interview/short-answer-card`） | 柔光有机渐变 | 逐词卡拉OK | 中性准确 | 只留人声 | 声波、引语卡、渐变网格 | 竖屏声波加逐词字幕 | 皮肤 |
| `pc-comic-timing` 喜剧节奏 | 对谈喜剧节拍（`interview/comic-timing`） | 复古波普 | 逐词弹出 | 夏日高调 | 综艺音效 | 反应特效字、推近强调 | 笑点前留半拍再推近 | 皮肤 |
| `pc-disagreement` 分歧保留 | 保留分歧（`interview/disagreement-preserved`） | 新闻编辑部 | 多人分色 | 低饱和高级灰 | 只留人声 | 分屏、清单勾选 | 分歧点不被剪成共识 | 皮肤 |
| `pc-contemplative` 沉思对话 | 留白对谈（`interview/contemplative-dialogue`） | 极简留白 | 极简细字 | 冬日冷蓝 | 环境声主导 | — | 长镜头不切换机位 | 皮肤 |
| `pc-clip-card` 金句切片 | 主张证据单元（`multiplatform/claim-proof`） | 黄白宣言 | 胶囊底逐词高亮 | 清透提亮 | 观点重音 | 引语卡、片尾引导 | 金句后紧跟它的依据 | 皮肤 |

### S11 课程录播

工作流 `raven-course-meeting` · 素材起点：课堂或录屏课程 · 关键信号：概念、证明、案例、章节

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `co-lab-demo` 实验演示 | 实验与演示（`course-meeting/lab-demonstration`） | 浅色科技看板 | 短语分组极简 | 清透提亮 | 只留人声 | 局部放大镜、步骤指示 | 关键操作局部放大 | 皮肤 |
| `co-proof-chain` 证明链 | 推导证明（`course-meeting/proof-chain`） | 极简留白 | 极简细字 | 中性准确 | 只留人声 | 公式推导、下划线描出 | 每步推导标出依据 | 皮肤 |
| `co-historical` 历史发展 | 知识演进（`course-meeting/historical-development`） | 剪报档案 | 纪录片说明字 | 档案褪色 | 纪实房间底噪 | 时间轴、静图运镜 | 时间轴上逐段点亮 | 皮肤 |
| `co-case-autopsy` 案例剖析 | 案例解剖（`course-meeting/case-autopsy`） | 红笔批改 | 关键词变色 | 中性准确 | 极简提示音 | 手绘圈注、因果图 | 红笔圈出失败的那一环 | 皮肤 |
| `co-contrast-pair` 对照组 | 对照辨析（`course-meeting/contrast-pair`） | 瑞士网格 | 关键词加粗放大 | 清透提亮 | 极简提示音 | 左右对比 | 两个例子只差一个变量 | 皮肤 |
| `co-chapter-index` 章节索引 | 流程地图（`course-meeting/process-map`） | 现代主义几何 | 短语分组极简 | 中性准确 | Lo-fi 底声 | 章节页、流程图、进度环 | 进度环告诉学生学到哪 | 皮肤 |

### S12 会议与发布会纪要

工作流 `raven-course-meeting` · 素材起点：会议录像 · 关键信号：决定、行动项、风险、未决问题

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `mt-decision-trace` 决策追踪 | 决策来路（`course-meeting/decision-trace`） | 蓝色专业 | 多人分色 | 中性准确 | 只留人声 | 清单勾选、时间轴 | 每个决定标出提出人和时间点 | 皮肤 |
| `mt-action-handoff` 行动交接 | 行动交接（`course-meeting/action-handoff`） | 瑞士网格 | 关键词变色 | 中性准确 | 极简提示音 | 清单勾选、姓名条 | 结尾一屏谁在何时做什么 | 皮肤 |
| `mt-risk-register` 风险登记 | 风险与阻塞（`course-meeting/risk-register`） | 黑底红行 | 短语分组极简 | 冷调科技 | 只留人声 | 规格表逐行点亮、框选标签 | 风险表逐行点亮 | 皮肤 |
| `mt-launch-recap` 发布会回顾 | 紧凑观点（`speech/crisp-argument`） | 深色流光 | 关键词加粗放大 | 黑金质感 | 商务明亮 | 巨型数字、片头标题、标志落版 | 三个发布数字依次亮起 | 皮肤 |
| `mt-open-questions` 未决问题 | 未决问题清单（`course-meeting/open-question-ledger`） | 牛皮纸便签 | 手写体整句 | 暖调生活 | 只留人声 | 问题卡、清单勾选 | 便签墙上留着未解决的问题 | 皮肤 |
| `mt-disagreement` 分歧线索 | 分歧脉络（`course-meeting/disagreement-thread`） | 新闻编辑部 | 多人分色 | 低饱和高级灰 | 只留人声 | 分屏、引语卡 | 反对意见原话完整保留 | 皮肤 |

## 商品与商业

### S13 实拍种草与推荐

工作流 `raven-commerce-story` · 素材起点：商品实拍＋本人讲解 · 关键信号：主张—证据表、使用动作、结果

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `pr-action-proof` 操作作证 | 操作本身作证（`commerce/action-proof`） | 瑞士网格 | 短语分组极简 | 商品真色 | 环境声主导 | 框选标签、数字滚动 | 计时器只出现在证明镜头上 | 皮肤 |
| `pr-quiet-reco` 安静推荐 | 克制的个人推荐（`commerce/quiet-recommendation`） | 生活画报 | 手写体整句 | 暖调生活 | Lo-fi 底声 | 荧光划线 | 只说一个真实理由 | 皮肤 |
| `pr-one-friction` 一个麻烦 | 一个具体麻烦（`commerce/one-friction`） | 暖橙几何 | 关键词加粗放大 | 清透提亮 | 极简提示音 | 问题卡、箭头指示 | 开头复现那个具体麻烦 | 皮肤 |
| `pr-result-first` 结果先行 | 先看可见结果（`commerce/result-first`） | 玻璃拟态 | 关键词变色 | 清透提亮 | 观点重音 | 分屏、方向擦除 | 先看结果再倒回过程 | 皮肤 |
| `pr-honest-compare` 条件对比 | 条件明确的比较（`commerce/honest-comparison`） | 现代主义几何 | 关键词变色 | 商品真色 | 极简提示音 | 左右对比、星级评分、用户评价卡 | 同条件左右并排 | 皮肤 |
| `pr-skeptic` 从怀疑到决定 | 带疑问试用（`commerce/skeptic-to-decision`） | 红笔批改 | 关键词变色 | 中性准确 | 只留人声 | 划掉改写、清单勾选 | 疑问一条条被划掉或保留 | 皮肤 |
| `pr-routine-fit` 融入日常 | 放进我的日常（`commerce/routine-integration`） | 纸感荧光 | 手写体整句 | 日系清新 | 原声吉他 | 时间轴 | 一天里它出现的三个时刻 | 皮肤 |
| `pr-outfit-choices` 穿搭选择 | 穿搭中的选择（`commerce/outfit-choices`） | 复古波普 | 逐词弹出 | 夏日高调 | 节拍驱动 | 分屏、卡点定格 | 每个卡点换一套 | 皮肤 |

### S14 直播带货切片

工作流 `raven-commerce-story` · 素材起点：直播回放 · 关键信号：SKU 出场与返场、价格条件、演示

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ls-single-sku` 单品证据切片 | 交易信息说清楚（`commerce/offer-with-context`） | 浅色科技看板 | 关键词变色 | 商品真色 | 只留人声 | 价格条件标签、框选标签 | 价格条件与有效期同屏 | 皮肤 |
| `ls-demo-first` 演示开头 | 操作本身作证（`commerce/action-proof`） | 黑黄重字 | 胶囊底逐词高亮 | 商品真色 | 观点重音 | 局部放大镜、价格条件标签 | 第一秒就是演示结果 | 皮肤 |
| `ls-qa-reply` 弹幕答疑 | 回答一个疑问（`commerce/comment-response`） | 弹幕二次元 | 弹幕式 | 清透提亮 | 极简提示音 | 社媒帖与评论卡、问题卡 | 先上观众问题再给原话回答 | 皮肤 |
| `ls-host-personality` 主播人设 | 人物瞬间（`highlights/live-personality`） | 萌系贴纸 | 表情点缀 | 清透提亮 | 综艺音效 | 反应特效字、推近强调 | 只保留主播真实反应 | 皮肤 |
| `ls-measure-proof` 实测数据 | 测量说清楚（`commerce/measurement-explained`） | 黑底红行 | 关键词加粗放大 | 商品真色 | 极简提示音 | 规格表逐行点亮、数字滚动 | 实测读数逐行点亮 | 皮肤 |
| `ls-calm-explainer` 冷静讲解版 | 只说一个有据卖点（`commerce/small-specific-claim`） | 极简留白 | 短语分组极简 | 中性准确 | 只留人声 | 来源标注 | 一个可证实的小主张 | 皮肤 |

### S15 开箱与 ASMR

工作流 `raven-commerce-story` · 素材起点：开箱实拍 · 关键信号：取物序列、物声、第一反应

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ub-window-asmr` 窗边 ASMR | 器物与声音（`commerce/object-sound`） | 极简留白 | 极简细字 | 日系清新 | 拟音前置 | — | 全片无旁白，只有开盒声 | 皮肤 |
| `ub-packing-list` 内容清点 | 实际包含什么（`commerce/packing-contents`） | 瑞士网格 | 关键词变色 | 商品真色 | 拟音前置 | 清单勾选、框选标签 | 每取出一件就在清单上打勾 | 皮肤 |
| `ub-first-impression` 第一印象 | 第一次接触（`commerce/first-impression`） | 生活画报 | 手写体整句 | 暖调生活 | 环境声主导 | 荧光划线 | 保留第一次拿起时的原话 | 皮肤 |
| `ub-unbox-to-use` 开箱到使用 | 从开箱到使用（`commerce/unbox-to-use`） | 浅色科技看板 | 短语分组极简 | 清透提亮 | 极简提示音 | 步骤指示、局部放大镜 | 开箱和第一次使用连成一序列 | 皮肤 |
| `ub-hands-only` 只有手 | 只看手和物（`commerce/hands-only-use`） | 新中式极简 | 竖排题字 | 莫兰迪 | 拟音前置 | — | 画面里只有手和物 | 皮肤 |
| `ub-mystery-reveal` 盲盒揭晓 | 具体感受（`commerce/sensory-reaction`） | 萌系贴纸 | 逐词弹出 | 夏日高调 | 综艺音效 | 表情弹出、彩纸粒子、闪光点缀 | 延迟露出，反应先于商品 | 皮肤 |

### S16 品牌广告后期包装

工作流 `raven-commerce-story` · 素材起点：品牌实拍或已生成镜头 · 关键信号：品牌标识、产品特写、宣言

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `bd-black-gold` 黑金质感 | 克制品牌观察（`commerce/brand-observation`） | 黑金高端 | 极简细字 | 黑金质感 | 电影化铺垫 | 标志落版、光泽扫过 | 光沿产品边缘走一次 | 皮肤 |
| `bd-manifesto` 品牌宣言 | 明确的品牌主张（`commerce/declared-manifesto`） | 黄白宣言 | 大字逐词冲击 | 高对比黑白 | 观点重音 | 重锤砸入、标志落版 | 宣言词逐词砸在黑白画面上 | 皮肤 |
| `bd-craft-process` 工艺过程 | 工艺中的选择（`commerce/craft-decisions`） | 生活画报 | 纪录片说明字 | 胶片暖褐 | 拟音前置 | 姓名条、来源标注 | 每道工序一次手部特写 | 皮肤 |
| `bd-material-journey` 材料之旅 | 材料到成品（`commerce/material-journey`） | 青绿山水 | 竖排题字 | 纪实自然 | 环境声主导 | 地图路线、墨晕转场 | 原料产地到成品的地图路线 | 皮肤 |
| `bd-founder` 创始人的选择 | 创始人的一次选择（`commerce/founder-choice`） | 黑白人物志 | 衬线引语 | 高对比黑白 | 纪实房间底噪 | 引语卡、章节页 | 一个艰难决定讲透 | 皮肤 |
| `bd-pop-campaign` 波普活动 | 物件与文化实践（`commerce/product-in-culture`） | 复古波普 | 综艺花字 | 夏日高调 | 节拍驱动 | 贴纸弹跳、形状遮罩开合、节拍脉冲 | 形状转场跟拍点 | 皮肤 |
| `bd-neo-chinese` 国潮新品 | 过去与现在对读（`commerce/archive-and-now`） | 朱红金饰 | 竖排题字 | 胶片暖褐 | 电影化铺垫 | 书法题字、墨晕转场、标志落版 | 书法题字落版 | 皮肤 |

### S17 本地生活探店

工作流 `raven-commerce-story` · 素材起点：到店实拍 · 关键信号：地点、菜品或服务、价格、排队

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ll-place-people` 店与人 | 地方与做事的人（`commerce/place-and-people`） | 生活画报 | 手写体整句 | 暖调生活 | 环境声主导 | 姓名条、地图路线 | 先拍门口再拍人 | 皮肤 |
| `ll-signature-dish` 招牌菜 | 具体感受（`commerce/sensory-reaction`） | 综艺彩字 | 关键词加粗放大 | 美食暖饱和 | 拟音前置 | 价格条件标签、推近强调 | 第一口的声音放大 | 皮肤 |
| `ll-honest-visit` 真实到店 | 喜欢但有保留（`commerce/experience-with-caveat`） | 牛皮纸便签 | 手写体整句 | 纪实自然 | 环境声主导 | 星级评分、清单勾选 | 优点和排队时长一起说 | 皮肤 |
| `ll-service-moment` 服务瞬间 | 服务发生的一刻（`commerce/service-moment`） | 极简留白 | 极简细字 | 胶片暖褐 | 纪实房间底噪 | — | 只拍一次服务的完整过程 | 皮肤 |
| `ll-route-guide` 路线攻略 | 有据行程（`vlog-journey/route-with-evidence`） | 暖橙几何 | 关键词变色 | 夏日高调 | 原声吉他 | 地图路线、步骤指示、价格条件标签 | 路线、价格、时间三件套 | 皮肤 |
| `ll-night-market` 夜市氛围 | 感官碎片（`vlog-journey/sensory-fragments`） | 霓虹夜 | 霓虹发光 | 夜景低噪 | 环境声主导 | 辉光 | 灯牌是唯一的光源 | 皮肤 |

### S18 房产与空间展示

工作流 `raven-commerce-story` · 素材起点：空间实拍＋户型 · 关键信号：动线、面积、光线、适合人群

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `re-space-walk` 空间漫游 | 空间认识（`vlog-journey/space-discovery`） | 极简留白 | 极简细字 | 清透提亮 | 环境声主导 | 框选标签 | 一镜走完动线 | 皮肤 |
| `re-floorplan` 户型标注 | 细节回到整体（`commerce/detail-and-whole`） | 蓝图线框 | 关键词变色 | 清透提亮 | 极简提示音 | 框选标签、规格表逐行点亮 | 户型图与实景交替 | 皮肤 |
| `re-lifestyle` 生活方式 | 放进我的日常（`commerce/routine-integration`） | 新中式极简 | 手写体整句 | 莫兰迪 | 原声吉他 | 渐显上浮 | 一天的光线在房间里移动 | 皮肤 |
| `re-before-after` 改造前后 | 一次改进的记录（`commerce/honest-improvement`） | 玻璃拟态 | 关键词加粗放大 | 清透提亮 | 观点重音 | 左右对比、方向擦除 | 同机位前后擦除 | 皮肤 |
| `re-premium` 高端楼盘 | 克制品牌观察（`commerce/brand-observation`） | 黑金高端 | 极简细字 | 黄金时刻 | 电影化铺垫 | 片头标题、光泽扫过 | 黄金时刻的外立面 | 皮肤 |
| `re-condition-led` 适合谁 | 先讲适用条件（`commerce/condition-led`） | 瑞士网格 | 短语分组极简 | 中性准确 | 只留人声 | 清单勾选、规格表逐行点亮 | 先说适合哪类家庭 | 皮肤 |

### S19 软件发布与功能宣传

工作流 `raven-software-tutorial` · 素材起点：真实界面录屏 · 关键信号：功能、版本差异、使用场景

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ap-device-showcase` 设备样机 | 证据型产品演示（`software/evidence-demo`） | 玻璃拟态 | 关键词加粗放大 | 清透提亮 | 商务明亮 | 设备样机、光标跟随放大、片尾引导 | 真实界面放进样机 | 皮肤 |
| `ap-release-delta` 版本变化 | 版本变化导览（`software/release-delta`） | 浅色科技看板 | 短语分组极简 | 中性准确 | 极简提示音 | 左右对比、点击涟漪 | 新旧界面同位对照 | 皮肤 |
| `ap-code-diff` 开发者变更 | 熟手技巧卡（`software/expert-shortcut`） | 黑绿终端 | 极简细字 | 冷调科技 | 极简提示音 | 代码差异、代码打字、按键提示 | 代码差异逐行亮起 | 皮肤 |
| `ap-kinetic-promo` 动感宣传 | 复杂界面分层讲解（`software/progressive-reveal`） | 深色流光 | 大字逐词冲击 | 冷调科技 | 节拍驱动 | 乱码解码、穿越推进、通知弹出、字重呼吸 | 功能名乱码解码而出 | 皮肤 |
| `ap-problem-story` 问题故事 | 单案例产品故事（`software/case-story`） | 暖橙几何 | 关键词变色 | 暖调生活 | 原声吉他 | 聊天气泡、光标跟随放大 | 从一条真实求助消息开始 | 皮肤 |
| `ap-3d-hero` 3D 主视觉 | 改前改后解释（`software/before-after`） | 科幻全息 | 极简细字 | 霓虹赛博 | 电影化铺垫 | 立体字、设备样机 | 界面卡片在空间里展开 | 皮肤 |

### S20 软件教程

工作流 `raven-software-tutorial` · 素材起点：操作录屏 · 关键信号：步骤、点击、报错、完成状态

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `tu-first-run` 首次上手 | 首次上手带练（`software/guided-first-run`） | 浅色科技看板 | 短语分组极简 | 清透提亮 | 只留人声 | 光标跟随放大、点击涟漪、步骤指示 | 每次点击前光标先停一下 | 皮肤 |
| `tu-silent` 无声演示 | 静音可跟做（`software/silent-walkthrough`） | 瑞士网格 | 关键词变色 | 中性准确 | Lo-fi 底声 | 按键提示、步骤指示 | 按键提示代替旁白 | 皮肤 |
| `tu-diagnose` 排错修复 | 证据排错（`software/diagnose-repair`） | 红笔批改 | 关键词变色 | 中性准确 | 极简提示音 | 手绘圈注、光标跟随放大 | 报错处红圈，修复后对勾 | 皮肤 |
| `tu-keyboard` 快捷键高手 | 键盘连续操作流（`software/keyboard-workflow`） | 黑绿终端 | 极简细字 | 冷调科技 | 复古游戏音 | 按键提示、代码打字 | 每个快捷键一次按键提示 | 皮肤 |
| `tu-before-after` 效果对比 | 改前改后解释（`software/before-after`） | 玻璃拟态 | 关键词加粗放大 | 清透提亮 | 观点重音 | 分屏、方向擦除 | 先看最终效果 | 皮肤 |
| `tu-concept-action` 概念到操作 | 概念落到操作（`software/concept-action`） | 白板马克笔 | 短语分组极简 | 清透提亮 | 只留人声 | 白板手绘、光标跟随放大 | 先画原理再进软件 | 皮肤 |

### S21 企业宣传与雇主品牌

工作流 `raven-documentary-story` · 素材起点：企业实拍与采访 · 关键信号：人物、价值观、数字、工艺

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `cp-workers` 普通员工 | 普通工作者（`commerce/ordinary-workers`） | 生活画报 | 纪录片说明字 | 纪实自然 | 纪实房间底噪 | 姓名条 | 每个人只拍他手上的活 | 皮肤 |
| `cp-values` 价值观在行动 | 价值通过行为出现（`commerce/values-in-action`） | 蓝色专业 | 短语分组极简 | 清透提亮 | 商务明亮 | 章节页、巨型数字 | 一个价值观对应一个真实动作 | 皮肤 |
| `cp-annual-numbers` 年度数字 | 证据解释（`speech/evidence-led`） | 深蓝冲击 | 大字逐词冲击 | 冷调科技 | 节拍驱动 | 数字滚动、巨型数字、柱状图 | 数字按节拍滚动 | 皮肤 |
| `cp-recruit` 招聘活力 | 长期关系的片段（`commerce/community-relationship`） | 暖橙几何 | 逐词弹出 | 夏日高调 | 节拍驱动 | 姓名条、贴纸弹跳、片尾引导 | 每个工位一个卡点 | 皮肤 |
| `cp-premium` 高端形象 | 没有英雄的协作（`commerce/brand-process-without-hero`） | 黑金高端 | 极简细字 | 黑金质感 | 电影化铺垫 | 标志落版、光泽扫过 | 不出现英雄人物，只有过程 | 皮肤 |
| `cp-health` 医疗健康 | 先讲适用条件（`commerce/condition-led`） | 医疗健康清新 | 短语分组极简 | 清透提亮 | 商务明亮 | 清单勾选、来源标注 | 每条健康主张都有来源 | 皮肤 |

## 生活与纪实

### S22 日常 Vlog

工作流 `raven-vlog-journey` · 素材起点：手机日常素材 · 关键信号：日常动作、任务、情绪变化

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `vd-ritual` 日常仪式 | 日常仪式（`vlog-journey/ordinary-ritual`） | 纸感荧光 | 手写体整句 | 暖调生活 | 原声吉他 | 手写笔顺 | 同一个动作每天出现一次 | 皮肤 |
| `vd-small-mission` 小任务 | 一件小事（`vlog-journey/small-mission`） | 萌系贴纸 | 逐词弹出 | 日系清新 | 综艺音效 | 清单勾选、表情弹出 | 开头立任务，结尾打勾 | 皮肤 |
| `vd-quiet-company` 安静陪伴 | 安静陪伴（`vlog-journey/quiet-company`） | 极简留白 | 极简细字 | 冬日冷蓝 | 环境声主导 | — | 不说话的十分钟 | 皮肤 |
| `vd-film-diary` 胶片日记 | 一天的质地（`vlog-journey/day-texture`） | 胶片片头字卡 | 电影字幕 | 胶片暖褐 | 原声吉他 | 胶片颗粒与光晕、漏光转场、胶片烧灼 | 每段以片孔字卡开头 | 皮肤 |
| `vd-expectation` 预期与现实 | 想象与现场（`vlog-journey/expectation-reality`） | 复古波普 | 关键词加粗放大 | 夏日高调 | 综艺音效 | 分屏、反应特效字 | 预期画面和现实分屏 | 皮肤 |
| `vd-process-notebook` 过程手账 | 过程手记（`vlog-journey/process-notebook`） | 牛皮纸便签 | 手写体整句 | 莫兰迪 | Lo-fi 底声 | 步骤指示、手绘圈注 | 每一步贴一张便签 | 皮肤 |

### S23 旅行

工作流 `raven-vlog-journey` · 素材起点：旅行素材 · 关键信号：路线、地点、当地人、天气

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `tv-route` 路线有据 | 有据行程（`vlog-journey/route-with-evidence`） | 现代主义几何 | 关键词变色 | 夏日高调 | 原声吉他 | 地图路线、姓名条 | 红线路线随行程画出 | 皮肤 |
| `tv-one-place` 一地久留 | 在一处停留（`vlog-journey/one-place-stay`） | 极简留白 | 竖排题字 | 胶片青绿 | 环境声主导 | — | 同一个窗口的早中晚 | 皮肤 |
| `tv-paper-atlas` 纸上地图 | 空间认识（`vlog-journey/space-discovery`） | 撕纸拼贴 | 手写体整句 | 暖调生活 | 原声吉他 | 地图路线、拼贴分层 | 剪纸地图上贴照片 | 皮肤 |
| `tv-local` 当地人 | 旅途相遇（`vlog-journey/local-encounter`） | 生活画报 | 双语上下 | 纪实自然 | 环境声主导 | 姓名条 | 当地人的原话加双语 | 皮肤 |
| `tv-landscape` 风景尺度 | 人与地方的尺度（`vlog-journey/landscape-human-scale`） | 青绿山水 | 极简细字 | 黄金时刻 | 节拍驱动 | 穿越推进、速度曲线 | 人始终在画面里作尺度 | 皮肤 |
| `tv-weather` 天气作角色 | 天气推动（`vlog-journey/weather-as-character`） | 宣纸水墨 | 竖排题字 | 冬日冷蓝 | 环境声主导 | 墨晕转场 | 雨的声音串起每一段 | 皮肤 |

### S24 美食制作

工作流 `raven-vlog-journey` · 素材起点：烹饪实拍 · 关键信号：步骤、配比、物声、成品

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `fd-recipe` 跟做菜谱 | 过程手记（`vlog-journey/process-notebook`） | 暖橙几何 | 关键词变色 | 美食暖饱和 | 拟音前置 | 步骤指示、数字滚动 | 每步给出克数和时间 | 皮肤 |
| `fd-asmr-cook` 无声烹饪 | 器物与声音（`commerce/object-sound`） | 新中式极简 | 竖排题字 | 美食暖饱和 | 拟音前置 | — | 只有刀与锅的声音 | 皮肤 |
| `fd-street` 街头烟火 | 感官碎片（`vlog-journey/sensory-fragments`） | 综艺彩字 | 综艺花字 | 港风夜色 | 节拍驱动 | 推近强调、反应特效字 | 出锅瞬间卡点 | 皮肤 |
| `fd-family-recipe` 家传味道 | 家庭纪念（`vlog-journey/family-keepsake`） | 老照片相册 | 手写体整句 | 胶片暖褐 | 原声吉他 | 静图运镜、手写笔顺 | 老照片里的同一道菜 | 皮肤 |
| `fd-nutrition` 轻食数据 | 测量说清楚（`commerce/measurement-explained`） | 医疗健康清新 | 关键词加粗放大 | 清透提亮 | 极简提示音 | 环形占比、巨型数字 | 热量与营养用环形图 | 皮肤 |
| `fd-fail-retry` 翻车再来 | 用错后学会（`commerce/mistake-and-learning`） | 爆梗红字 | 逐词弹出 | 录像带复古 | 综艺音效 | 反应特效字、定格 | 翻车瞬间定格 | 皮肤 |

### S25 健身与运动教学

工作流 `raven-event-highlights` · 素材起点：训练实拍 · 关键信号：动作要点、计数、进步、错误动作

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ft-form` 动作拆解 | 动作拆解（`highlights/technique-breakdown`） | 浅色科技看板 | 关键词变色 | 清透提亮 | 只留人声 | 箭头指示、定格、局部放大镜 | 关键角度定格加箭头 | 皮肤 |
| `ft-workout-beat` 跟练节拍 | 训练变化（`highlights/training-progress`） | 电竞 HUD | 大字逐词冲击 | 夏日高调 | 节拍驱动 | 进度环、数字滚动 | 倒计时环跟着拍点走 | 皮肤 |
| `ft-progress` 进步日记 | 前后变化（`vlog-journey/before-after-context`） | 瑞士网格 | 短语分组极简 | 中性准确 | 原声吉他 | 折线图、分屏 | 同角度第 1 天与第 90 天 | 皮肤 |
| `ft-correction` 错误动作纠正 | 误区纠偏（`course-meeting/misconception-repair`） | 红笔批改 | 关键词变色 | 清透提亮 | 只留人声 | 红笔批改、分屏 | 错误与正确同屏并排 | 皮肤 |
| `ft-outdoor-film` 户外胶片 | 瞬间回放（`highlights/moment-replay`） | 胶片片头字卡 | 电影字幕 | 胶片青绿 | 电影化铺垫 | 速度曲线、胶片颗粒与光晕 | 落地前一刻变速 | 皮肤 |
| `ft-calm-yoga` 舒缓瑜伽 | 安静陪伴（`vlog-journey/quiet-company`） | 柔光有机渐变 | 极简细字 | 日系清新 | Lo-fi 底声 | 进度环、极光流动 | 呼吸计数代替口令 | 皮肤 |

### S26 婚礼、家庭与纪念

工作流 `raven-vlog-journey` · 素材起点：活动与家庭素材 · 关键信号：仪式时刻、原声、旧照片

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `fe-golden-wedding` 黄金时刻婚礼 | 共同瞬间（`vlog-journey/collective-moment`） | 生活画报 | 电影字幕 | 黄金时刻 | 电影化铺垫 | 片头标题、漏光转场、漏光叠加 | 誓词原声压过音乐 | 皮肤 |
| `fe-keepsake` 家庭纪念 | 家庭纪念（`vlog-journey/family-keepsake`） | 老照片相册 | 手写体整句 | 档案褪色 | 原声吉他 | 静图运镜、照片 2.5D 视差 | 老照片 2.5D 动起来 | 机制 |
| `fe-kid-growth` 成长记录 | 重访同一处（`vlog-journey/time-return`） | 萌系贴纸 | 逐词弹出 | 绘本柔彩 | 原声吉他 | 时间轴、贴纸弹跳 | 同一个门框的身高线 | 皮肤 |
| `fe-party` 派对高能 | 参与者体验（`vlog-journey/event-experience`） | 复古波普 | 综艺花字 | 夏日高调 | 节拍驱动 | 彩纸粒子、节拍脉冲 | 干杯时彩纸只出现一次 | 皮肤 |
| `fe-letter` 写给你的信 | 写给某人的片段（`vlog-journey/memory-letter`） | 牛皮纸便签 | 手写体整句 | 胶片暖褐 | 纪实房间底噪 | 手写笔顺 | 手写信逐字出现 | 皮肤 |
| `fe-mono-classic` 黑白经典 | 多人同一细节（`vlog-journey/shared-detail`） | 默片字幕卡 | 电影字幕 | 高对比黑白 | 纪实房间底噪 | 章节页 | 默片字卡分章 | 皮肤 |

### S27 人物纪录

工作流 `raven-documentary-story` · 素材起点：纪实素材与采访 · 关键信号：人物行为、地点、档案、声音

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `dc-observational` 观察式 | 连续观察（`documentary/observational-sequence`） | 极简留白 | 纪录片说明字 | 纪实自然 | 环境声主导 | — | 不加任何图形 | 皮肤 |
| `dc-hands-craft` 手艺 | 手上的经验（`documentary/hands-craft`） | 新中式极简 | 竖排题字 | 胶片暖褐 | 拟音前置 | 姓名条、虚实转换 | 每个手艺动作完整保留 | 皮肤 |
| `dc-archive-present` 档案与现在 | 档案与当下（`documentary/archive-present`） | 剪报档案 | 纪录片说明字 | 档案褪色 | 纪实房间底噪 | 静图运镜、分屏 | 同一地点今昔分屏 | 皮肤 |
| `dc-voice-led` 声音主导 | 由自己的话带路（`documentary/voice-led`） | 黑白人物志 | 电影字幕 | 高对比黑白 | 纪实房间底噪 | 引语卡 | 黑场中先听到声音 | 皮肤 |
| `dc-collective` 群像 | 群像（`documentary/collective-portrait`） | 生活画报 | 纪录片说明字 | 纪实自然 | 环境声主导 | 姓名条、分屏 | 九宫格群像收尾 | 皮肤 |
| `dc-workday` 一天的工作 | 一个工作日（`documentary/workday`） | 瑞士网格 | 纪录片说明字 | 中性准确 | 环境声主导 | 时间轴、姓名条 | 时钟时间作章节 | 皮肤 |

### S28 新闻调查与解释

工作流 `raven-documentary-story` · 素材起点：采访、档案与网页证据 · 关键信号：主张、证据、来源、更正

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ni-trail` 调查线索 | 调查线索（`documentary/investigative-trail`） | 剪报档案 | 纪录片说明字 | 低饱和高级灰 | 悬疑低鸣 | 手绘圈注、因果图、来源标注 | 红线把证据连起来 | 皮肤 |
| `ni-claim-evidence` 主张与证据 | 说法与证据（`documentary/claim-evidence`） | 新闻编辑部 | 衬线引语 | 中性准确 | 资讯底乐 | 引语卡、来源标注、框选标签 | 每个主张旁边是它的证据 | 皮肤 |
| `ni-verification` 核实路径 | 核验路径（`documentary/verification-path`） | 黑绿终端 | 关键词变色 | 冷调科技 | 极简提示音 | 浏览器框、光标跟随放大、框选标签 | 复现查证的每一步 | 皮肤 |
| `ni-riso-explainer` 套印解释 | 机制解释（`documentary/mechanism-explainer`） | 双色套印 | 关键词加粗放大 | 胶片青绿 | 资讯底乐 | 拼贴分层、网点印刷、地图路线 | 网点印刷的拼贴解释 | 皮肤 |
| `ni-correction` 更正说明 | 公开更正（`documentary/correction`） | 红笔批改 | 短语分组极简 | 中性准确 | 只留人声 | 划掉改写 | 旧结论被明确划掉 | 皮肤 |
| `ni-numbers` 数字说清 | 数字的尺度（`documentary/numbers`） | 浅色科技看板 | 关键词变色 | 清透提亮 | 极简提示音 | 柱状图、巨型数字、来源标注 | 每个图表标口径 | 皮肤 |

### S29 活动、展会与演出

工作流 `raven-event-highlights` · 素材起点：活动多源素材 · 关键信号：议程、来宾、高潮、演示

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ev-chapters` 活动章节 | 活动章节（`vlog-journey/event-chapters`） | 现代主义几何 | 短语分组极简 | 清透提亮 | 商务明亮 | 章节页、姓名条 | 按议程章节组织 | 皮肤 |
| `ev-behind` 幕后 | 幕后准备（`vlog-journey/behind-the-event`） | 档案打字 | 纪录片说明字 | 纪实自然 | 环境声主导 | 时间轴、打字机 | 倒计时时间码 | 皮肤 |
| `ev-energy` 高能回顾 | 共同瞬间（`vlog-journey/collective-moment`） | 深色流光 | 3D 跟随 | 霓虹赛博 | 节拍驱动 | 节拍脉冲、穿越推进 | 高潮镜头落在重拍 | 机制 |
| `ev-voices` 来宾声音 | 多声部现场（`vlog-journey/voices-of-event`） | 生活画报 | 多人分色 | 暖调生活 | 环境声主导 | 姓名条、引语卡 | 每位来宾一句原话 | 皮肤 |
| `ev-expo` 展会产品 | 功能落到动作（`commerce/feature-to-action`） | 玻璃拟态 | 关键词变色 | 商品真色 | 商务明亮 | 框选标签、姓名条 | 展台上的真实演示 | 皮肤 |
| `ev-performance` 演出完整 | 表演的呼吸（`vlog-journey/performance-breath`） | 胶片片头字卡 | 极简细字 | 港风夜色 | 环境声主导 | — | 完整保留一首歌 | 皮肤 |

## 娱乐与叙事后期

### S30 影视解说

工作流 `raven-film-recap` · 素材起点：已授权影视素材 · 关键信号：因果、线索、人物弧、名场面

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `fr-causal` 因果主线 | 因果主线（`film-recap/causal-spine`） | 胶片片头字卡 | 电影字幕 | 中性准确 | 电影化铺垫 | 章节页 | 每段以“于是”连接 | 皮肤 |
| `fr-clue` 线索悬疑 | 线索递进悬疑（`film-recap/clue-suspense`） | 剪报档案 | 关键词变色 | 低饱和高级灰 | 悬疑低鸣 | 手绘圈注、定格 | 线索定格圈出，答案延后 | 皮肤 |
| `fr-arc` 人物弧光 | 人物选择与弧线（`film-recap/character-arc`） | 黑白人物志 | 衬线引语 | 中性准确 | 电影化铺垫 | 章节页、引语卡 | 人物三次选择三张卡 | 皮肤 |
| `fr-irony` 戏剧反讽 | 观众知情差（`film-recap/dramatic-irony`） | 红笔批改 | 关键词加粗放大 | 中性准确 | 悬疑低鸣 | 分屏、框选标签 | 观众知道的写在角落 | 皮肤 |
| `fr-comic` 吐槽反应 | 喜剧铺垫与反应（`film-recap/comic-reaction`） | 爆梗红字 | 综艺花字 | 中性准确 | 综艺音效 | 反应特效字、推近强调、定格 | 名场面定格配吐槽 | 皮肤 |
| `fr-close-reading` 场景细读 | 单场景细读（`film-recap/scene-close-reading`） | 极简留白 | 极简细字 | 中性准确 | 纪实房间底噪 | 局部放大镜、框选标签、聚光压暗 | 一场戏逐镜放大细节 | 皮肤 |
| `fr-micro` 一分钟讲完 | 短时长完整故事（`film-recap/micro-complete`） | 黑黄重字 | 大字逐词冲击 | 中性准确 | 节拍驱动 | 片头标题 | 一分钟一个完整因果 | 皮肤 |

### S31 短剧后期包装与切条

工作流 `raven-drama-production` · 素材起点：已剪短剧正片 · 关键信号：钩子冲突、人物出场、集尾悬念

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `dp-hook-cut` 投流钩子切条 | 开场受控对照（`multiplatform/hook-controlled`） | 爆梗红字 | 胶囊底逐词高亮 | 中性准确 | 观点重音 | 片头标题、片尾引导 | 前三秒是全集最强冲突 | 皮肤 |
| `dp-previously` 前情提要 | 分层概览（`multiplatform/layered-summary`） | 胶片片头字卡 | 电影字幕 | 中性准确 | 悬疑低鸣 | 章节页、闪白闪黑 | 黑场字卡“上集” | 皮肤 |
| `dp-trailer` 预告片 | 诚实预告（`multiplatform/teaser-honesty`） | 黑金高端 | 极简细字 | 中性准确 | 电影化铺垫 | 光泽扫过、片头标题、闪白闪黑 | 声音先入，片名最后 | 皮肤 |
| `dp-character-card` 人物出场卡 | 系列识别（`multiplatform/series-identity`） | 黑黄重字 | 关键词加粗放大 | 中性准确 | 观点重音 | 定格、姓名条、重锤砸入 | 定格加人物身份牌 | 皮肤 |
| `dp-ancient-title` 古装题签 | 系列识别（`multiplatform/series-identity`） | 宣纸水墨 | 竖排题字 | 胶片暖褐 | 电影化铺垫 | 书法题字、墨晕转场、雨雪 | 书法剧名与墨晕 | 皮肤 |
| `dp-vertical` 竖屏重构 | 明确主体窗口（`multiplatform/subject-window`） | 极简留白 | 多人分色 | 中性准确 | 纪实房间底噪 | 主体跟随重构图 | 人物始终在竖屏中 | 机制 |
| `dp-commentary` 短剧解说 | 连续剧集承接（`film-recap/serial-bridge`） | 综艺彩字 | 综艺花字 | 中性准确 | 综艺音效 | 章节页、反应特效字 | 每集结尾留一个问题 | 皮肤 |

### S32 综艺与搞笑段子

工作流 `raven-event-highlights` · 素材起点：综艺或段子原片 · 关键信号：笑点、反应、重复梗

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `va-variety` 综艺花字 | 人物瞬间（`highlights/live-personality`） | 综艺彩字 | 综艺花字 | 夏日高调 | 综艺音效 | 反应特效字、推近强调、表情弹出 | 反应花字只跟真实笑点 | 皮肤 |
| `va-deadpan` 冷面幽默 | 笑点延迟（`pacing/comic-delay`） | 极简留白 | 极简细字 | 中性准确 | 静默断点 | 定格 | 笑点后留两秒空白 | 皮肤 |
| `va-meme-loop` 重复梗卡点 | 连续回调（`highlights/callback-thread`） | 爆梗红字 | 大字逐词冲击 | 录像带复古 | 节拍驱动 | 推近强调、震动、卡点定格 | 同一句话按节拍重复 | 皮肤 |
| `va-retro-tv` 老电视 | 直播挑战（`highlights/live-challenge`） | 像素复古 | 打字机 | 录像带复古 | 复古游戏音 | 录像带、片头标题 | 像素关卡字卡分章 | 皮肤 |
| `va-danmaku` 弹幕吐槽 | 观众问答（`highlights/chat-response`） | 弹幕二次元 | 弹幕式 | 日系清新 | 综艺音效 | 社媒帖与评论卡、表情弹出 | 弹幕只用真实评论 | 皮肤 |
| `va-duo` 双人对口 | 对谈喜剧节拍（`interview/comic-timing`） | 萌系贴纸 | 多人分色 | 暖调生活 | 综艺音效 | 分屏 | 两人分色字幕 | 皮肤 |

### S33 游戏高光

工作流 `raven-event-highlights` · 素材起点：游戏录屏 · 关键信号：决策、连招、经济曲线、失误

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `gm-esports` 电竞 HUD | 残局判断（`highlights/clutch-decision`） | 电竞 HUD | 故障分离 | 霓虹赛博 | 节拍驱动 | 姓名条、数字滚动、速度曲线 | 残局决策慢放 | 皮肤 |
| `gm-combo` 连招可读 | 连招可读（`highlights/combo-readability`） | 像素复古 | 关键词加粗放大 | 中性准确 | 复古游戏音 | 按键提示、箭头指示、定格 | 按键序列同屏 | 皮肤 |
| `gm-comeback` 翻盘弧线 | 局势翻转（`highlights/comeback-arc`） | 科幻全息 | 大字逐词冲击 | 霓虹赛博 | 电影化铺垫 | 折线图、故障转场 | 经济曲线反转 | 皮肤 |
| `gm-speedrun` 速通计时 | 挑战尝试（`highlights/speedrun-attempt`） | 黑绿终端 | 极简细字 | 中性准确 | 复古游戏音 | 数字滚动、时间轴 | 分段计时器常驻 | 皮肤 |
| `gm-world` 世界探索 | 探索发现（`highlights/world-discovery`） | 柔光有机渐变 | 极简细字 | 黄金时刻 | 环境声主导 | 片头标题 | 第一次看见远景时不说话 | 皮肤 |
| `gm-failure` 失败教学 | 失误复盘（`highlights/learning-from-failure`） | 红笔批改 | 关键词变色 | 中性准确 | 极简提示音 | 红笔批改、定格 | 失误点红笔复盘 | 皮肤 |

### S34 体育高光

工作流 `raven-event-highlights` · 素材起点：比赛录像 · 关键信号：关键回合、转折、配合、回放身份

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `sp-replay` 关键回放 | 瞬间回放（`highlights/moment-replay`） | 深蓝冲击 | 关键词加粗放大 | 夏日高调 | 电影化铺垫 | 速度曲线、定格、姓名条 | 回放必标“回放” | 皮肤 |
| `sp-technique` 技术拆解 | 动作拆解（`highlights/technique-breakdown`） | 蓝图线框 | 关键词变色 | 中性准确 | 只留人声 | 箭头指示、跟踪标签 | 跟踪标签标出跑位 | 机制 |
| `sp-turning-point` 转折点 | 转折回顾（`highlights/turning-point`） | 新闻编辑部 | 短语分组极简 | 中性准确 | 悬疑低鸣 | 折线图、章节页 | 比分曲线上的转折 | 皮肤 |
| `sp-underdog` 弱者叙事 | 弱势应对（`highlights/underdog-context`） | 胶片片头字卡 | 电影字幕 | 胶片暖褐 | 电影化铺垫 | 姓名条、时间轴 | 赛前背景先于比赛 | 皮肤 |
| `sp-teamwork` 团队配合 | 配合链条（`highlights/team-combination`） | 浅色科技看板 | 短语分组极简 | 清透提亮 | 极简提示音 | 箭头指示、流程图 | 传球路线画线 | 皮肤 |
| `sp-fan-energy` 现场声浪 | 完整回合（`highlights/complete-possession`） | 黑黄重字 | 大字逐词冲击 | 夏日高调 | 节拍驱动 | 节拍脉冲、震动 | 进球时全场声音先于画面 | 皮肤 |

### S35 音乐卡点与 MV 混剪

工作流 `raven-music-montage` · 素材起点：多素材＋音乐 · 关键信号：拍点、乐句、视觉母题、歌词

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `mm-beat-hit` 强拍卡点 | 准备与落点（`music-montage/anticipation-hit`） | 深色流光 | 歌词卡拉OK | 霓虹赛博 | 节拍驱动 | 卡点定格、甩镜 | 切点落在强拍前一帧 | 皮肤 |
| `mm-graphic-rhyme` 图形押韵 | 图形押韵（`music-montage/graphic-rhyme`） | 瑞士网格 | 极简细字 | 中性准确 | 节拍驱动 | 匹配剪辑辅助、双色调 | 形状相同处换镜 | 机制 |
| `mm-color-thread` 颜色线索 | 色彩线索（`music-montage/color-thread`） | 柔光有机渐变 | 极简细字 | 胶片青绿 | 节拍驱动 | 叠化、噪点质感 | 一种颜色贯穿全片 | 皮肤 |
| `mm-lyric-image` 歌词画面 | 歌词意象（`music-montage/lyric-image`） | 宣纸水墨 | 竖排题字 | 胶片暖褐 | 节拍驱动 | 书法题字、墨晕转场 | 歌词关键词书法显出 | 皮肤 |
| `mm-memory` 回忆碎片 | 记忆碎片（`music-montage/memory-fragments`） | 老照片相册 | 极简细字 | 档案褪色 | 节拍驱动 | 胶片颗粒与光晕、漏光转场 | 漏光转场连接碎片 | 皮肤 |
| `mm-dance` 舞蹈乐句 | 舞句完整（`music-montage/dance-phrase`） | 酸绿花字 | 逐词弹出 | 夏日高调 | 节拍驱动 | 速度曲线、节拍脉冲 | 动作在乐句末定格 | 皮肤 |
| `mm-quiet-build` 安静递进 | 克制蓄积（`music-montage/quiet-build`） | 极简留白 | 电影字幕 | 冬日冷蓝 | 节拍驱动 | 叠化、速度曲线 | 前半无切点，后半加速 | 皮肤 |

## 版本与适配

### S36 多平台拆条

工作流 `raven-multiplatform-batch` · 素材起点：已有成片 · 关键信号：独立成立的段落、主体位置、画幅

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `mp-claim-proof` 观点加证据短条 | 主张证据单元（`multiplatform/claim-proof`） | 黑黄重字 | 关键词加粗放大 | 清透提亮 | 观点重音 | 引语卡、片尾引导、逐词升起 | 主张后三秒内给证据 | 皮肤 |
| `mp-silent-readable` 静音可读 | 无声可理解（`multiplatform/silent-readable`） | 瑞士网格 | 关键词加粗放大 | 清透提亮 | 只留人声 | 片头标题 | 关掉声音也看得懂 | 皮肤 |
| `mp-series` 系列标识 | 系列识别（`multiplatform/series-identity`） | 暖橙几何 | 渐变填充 | 暖调生活 | 极简提示音 | 片头标题、片尾引导、标志落版 | 每条同一个片头三秒 | 皮肤 |
| `mp-vertical-window` 竖屏主体窗 | 明确主体窗口（`multiplatform/subject-window`） | 极简留白 | 短语分组极简 | 中性准确 | 只留人声 | 主体跟随重构图 | 主体始终在安全区内 | 机制 |
| `mp-teaser` 诚实预告 | 诚实预告（`multiplatform/teaser-honesty`） | 胶片片头字卡 | 电影字幕 | 中性准确 | 悬疑低鸣 | 片头标题、闪白闪黑 | 预告里的每个画面正片都有 | 皮肤 |
| `mp-expert-recap` 专家速览 | 熟练者速查（`multiplatform/expert-recap`） | 浅色科技看板 | 关键词变色 | 清透提亮 | 资讯底乐 | 清单勾选、章节页 | 一屏三点 | 皮肤 |

### S37 本地化与双语

工作流 `raven-localization` · 素材起点：已有成片＋字幕 · 关键信号：术语、文化项、画面文字、口型

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `lo-paired` 双语对照 | 双语对照（`localization/bilingual-paired`） | 蓝色专业 | 双语上下 | 中性准确 | 只留人声 | — | 两种语言同时完整 | 皮肤 |
| `lo-term-first` 术语优先 | 术语双标（`localization/term-first-caption`） | 浅色科技看板 | 外语为主中文小字 | 中性准确 | 只留人声 | 框选标签 | 术语首现给原文和解释 | 皮肤 |
| `lo-footnote` 文化注释 | 轻量文化注释（`localization/cultural-footnote`） | 生活画报 | 双语上下 | 中性准确 | 只留人声 | 来源标注 | 文化梗用角注解释 | 皮肤 |
| `lo-revoice` 配音口型 | 可见口型译配（`localization/lip-sync-performance`） | 极简留白 | 极简细字 | 中性准确 | 只留人声 | — | 口型同步，不加字幕 | 机制 |
| `lo-screen-text` 画面文字本地化 | 屏幕文字适配（`localization/screen-text-locale`） | 瑞士网格 | 短语分组极简 | 中性准确 | 只留人声 | 跟踪打码、渐显上浮 | 画面原文字被替换为目标语 | 机制 |
| `lo-sdh` 无障碍字幕 | 声音信息字幕（`localization/sdh-evidence`） | 新闻编辑部 | 无障碍大字 | 中性准确 | 只留人声 | — | 声音描述写进字幕 | 皮肤 |

### S38 精华版与节奏重构

工作流 `raven-pacing-restructure` · 素材起点：已有成片 · 关键信号：主张链、气口、章节、音乐密度

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `cd-claim-chain` 主张链压缩 | 论证骨架（`pacing/claim-chain`） | 瑞士网格 | 关键词加粗放大 | 中性准确 | 只留人声 | 章节页 | 每段只留主张和最强依据 | 皮肤 |
| `cd-breath` 保留气口 | 段落换气（`pacing/breath-reset`） | 极简留白 | 短语分组极简 | 中性准确 | 纪实房间底噪 | — | 缩短但不删呼吸 | 皮肤 |
| `cd-timed-chapter` 定时章节 | 章节预算（`multiplatform/timed-chapter`） | 现代主义几何 | 短语分组极简 | 中性准确 | Lo-fi 底声 | 章节页、进度环 | 每章固定时长 | 皮肤 |
| `cd-backtrace` 结果倒叙 | 结果回溯（`pacing/result-backtrace`） | 黑黄重字 | 关键词加粗放大 | 中性准确 | 观点重音 | 片头标题、闪白闪黑 | 先给结果再回到起点 | 皮肤 |
| `cd-music-density` 音乐密度 | 稀密释放（`pacing/music-density-release`） | 深色流光 | 极简细字 | 中性准确 | 节拍驱动 | 节拍脉冲 | 音乐决定哪里加速 | 皮肤 |
| `cd-silence` 静默对比 | 寂静对照（`pacing/silence-contrast`） | 黑白人物志 | 电影字幕 | 高对比黑白 | 静默断点 | — | 最重要的一句前留白 | 皮肤 |

### S39 参考复刻

工作流 `raven-reference-style` · 素材起点：目标素材＋参考片 · 关键信号：参考的节奏、色板、构图、声画关系

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `rf-proof-ladder` 证据阶梯 | 证据阶梯（`reference/proof-ladder`） | 浅色科技看板 | 关键词变色 | 中性准确 | 极简提示音 | 步骤指示、来源标注 | 证据逐级加码 | 皮肤 |
| `rf-sound-first` 声先于画 | 先声后画（`reference/sound-before-image`） | 胶片片头字卡 | 电影字幕 | 中性准确 | 悬疑低鸣 | 闪白闪黑 | 每段先黑场听声 | 皮肤 |
| `rf-palette` 克制色板 | 克制色域（`reference/restrained-palette`） | 极简留白 | 极简细字 | 低饱和高级灰 | 纪实房间底噪 | — | 只借参考片的色板 | 皮肤 |
| `rf-kinetic-limit` 有限动效 | 文字运动适配（`reference/kinetic-with-limit`） | 酸绿花字 | 逐词弹出 | 中性准确 | 观点重音 | 重锤砸入、推近强调 | 只借参考片的大字节奏 | 皮肤 |
| `rf-long-take` 长镜注意力 | 长镜注意力（`reference/long-take-attention`） | 新中式极简 | 竖排题字 | 胶片青绿 | 环境声主导 | — | 借参考片的长镜头长度 | 皮肤 |
| `rf-shape-rhyme` 形状押韵 | 形状押韵（`reference/shape-rhyme`） | 现代主义几何 | 极简细字 | 中性准确 | 节拍驱动 | 匹配剪辑辅助 | 借参考片的形状匹配转场 | 机制 |

## 图文与生成补足

### S40 图文与照片成片

工作流 `raven-script-generation` · 素材起点：照片与文字 · 关键信号：地点、时间、细节、引用

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ph-spatial-window` 空间窗口 | 空间窗口（`generation/spatial-window`） | 极简留白 | 极简细字 | 中性准确 | 环境声主导 | 静图运镜 | 多张同地照片拼出空间 | 皮肤 |
| `ph-archive-letter` 照片来信 | 照片来信（`generation/archive-letter`） | 老照片相册 | 手写体整句 | 档案褪色 | 原声吉他 | 静图运镜、手写笔顺 | 旧照配手写信 | 皮肤 |
| `ph-time-pair` 两张照片的时间 | 两张照片的时间（`generation/time-pair`） | 瑞士网格 | 纪录片说明字 | 中性准确 | 纪实房间底噪 | 分屏、方向擦除 | 同角度两个年份擦除对比 | 皮肤 |
| `ph-annotated-proof` 图片举证 | 图片举证（`generation/annotated-proof`） | 红笔批改 | 关键词变色 | 中性准确 | 极简提示音 | 手绘圈注、局部放大镜 | 圈出图中的证据 | 皮肤 |
| `ph-parallax` 动态照片 | 静止凝视（`generation/still-attention`） | 生活画报 | 极简细字 | 胶片暖褐 | 环境声主导 | 照片 2.5D 视差 | 照片里的空间动起来 | 机制 |
| `ph-gallery` 安静画廊 | 安静画廊（`generation/quiet-gallery`） | 新中式极简 | 竖排题字 | 莫兰迪 | 纪实房间底噪 | 渐显上浮 | 一张一张不催促 | 皮肤 |

### S41 动画讲解与数据可视化

工作流 `raven-script-generation` · 素材起点：脚本或数据 · 关键信号：概念关系、数值、步骤、比喻

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `ea-whiteboard` 白板动画 | 逐步说明（`generation/step-reveal`） | 白板马克笔 | 短语分组极简 | 清透提亮 | Lo-fi 底声 | 白板手绘、箭头指示、描边书写 | 手画出每个概念 | 皮肤 |
| `ea-paper-cutout` 剪纸寓言 | 插画寓言（`generation/illustrated-fable`） | 撕纸拼贴 | 手写体整句 | 暖调生活 | 原声吉他 | 拼贴分层、撕纸转场 | 剪纸人物讲寓言 | 皮肤 |
| `ea-data-story` 数据故事 | 数字到尺度（`generation/number-to-scale`） | 浅色科技看板 | 关键词变色 | 清透提亮 | 极简提示音 | 柱状图、数字滚动、地图路线 | 数字换算成看得见的尺度 | 皮肤 |
| `ea-cause-map` 因果地图 | 因果展开（`generation/cause-map`） | 蓝图线框 | 短语分组极简 | 冷调科技 | Lo-fi 底声 | 因果图、流程图 | 一张图越画越完整 | 皮肤 |
| `ea-math` 数学动画 | 比喻后返回（`generation/analogy-with-return`） | 极简留白 | 极简细字 | 中性准确 | 只留人声 | 公式推导 | 类比后回到公式 | 皮肤 |
| `ea-3d-product` 3D 产品原理 | 产品形态观察（`generation/product-form-study`） | 科幻全息 | 极简细字 | 霓虹赛博 | 电影化铺垫 | 产品转台、框选标签 | 爆炸图拆解结构 | 皮肤 |
| `ea-kinetic-type` 动态字体 | 一个问题的解释（`generation/one-question-explainer`） | 深蓝冲击 | 大字逐词冲击 | 中性准确 | 观点重音 | 重锤砸入、乱码解码 | 整片只有字 | 皮肤 |

### S42 数字人口播

工作流 `raven-script-generation` · 素材起点：脚本＋授权形象 · 关键信号：讲解段、演示段、对话角色

| 风格包 | 方法卡 | 设计系统 | 字幕 | 影调 | 声音 | 组件 | 签名手法 | 成本 |
|---|---|---|---|---|---|---|---|---|
| `av-explainer` 讲解员 | 讲解型数字人（`generation/presenter-explainer`） | 浅色科技看板 | 关键词变色 | 清透提亮 | 只留人声 | 姓名条、柱状图、背景虚化或替换 | 数字人只讲，证据用真实图表 | 机制 |
| `av-demo-handoff` 演示交接 | 讲解与演示交接（`generation/presenter-demo-handoff`） | 玻璃拟态 | 短语分组极简 | 清透提亮 | Lo-fi 底声 | 画中画、光标跟随放大、色键抠像 | 讲到操作就交给真实录屏 | 机制 |
| `av-accessible` 无障碍讲解 | 清楚易读讲述（`generation/accessible-presenter`） | 医疗健康清新 | 无障碍大字 | 中性准确 | 只留人声 | — | 大字幕加慢语速 | 机制 |
| `av-two-voice` 双人对话 | 双声部对话（`generation/two-voice-dialogue`） | 暖橙几何 | 多人分色 | 暖调生活 | Lo-fi 底声 | 分屏 | 两个角色分色对话 | 机制 |
| `av-character` 角色旁白 | 角色化讲述（`generation/character-narrator`） | 萌系贴纸 | 逐词弹出 | 绘本柔彩 | 原声吉他 | 贴纸弹跳 | 卡通角色串场 | 机制 |
| `av-local-repair` 局部修补 | 讲解局部重录（`generation/presenter-local-repair`） | 蓝色专业 | 短语分组极简 | 中性准确 | 只留人声 | — | 只重生成说错的那一句 | 机制 |

