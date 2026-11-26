"""Scenario and style-pack catalog for reel-scribe (design stage, authored-unvalidated).

Each pack tuple: (id, name, method, rhythm, design_system, caption, look, sound, components, signature)
method = "<styles domain>/<existing card id>" and must exist in styles/<domain>/catalog.json.
"""

# id: (name, domain, workflow, material_start, key_signals, requires)
SCENARIOS = {
    "S01": ("知识科普口播", "真人口播与知识表达", "raven-speech-edit", "单人口播原片", "步骤、概念关系、误区、数值", []),
    "S02": ("观点评论", "真人口播与知识表达", "raven-speech-edit", "单人口播原片", "主张、转折、反例、引语", []),
    "S03": ("数码家电测评", "真人口播与知识表达", "raven-speech-edit", "口播原片＋产品 B-roll", "规格对、测量读数、比较、缺点", []),
    "S04": ("教学讲解", "真人口播与知识表达", "raven-speech-edit", "讲课原片", "步骤、例题、常见错误、检验方法", []),
    "S05": ("个人经历与情感口播", "真人口播与知识表达", "raven-speech-edit", "口播原片＋旧照片或 B-roll", "故事节拍、情绪峰、停顿", []),
    "S06": ("资讯快讯播报", "真人口播与知识表达", "raven-speech-edit", "播报原片＋来源材料", "事实条目、来源、更新、地点", []),
    "S07": ("财经商业分析", "真人口播与知识表达", "raven-speech-edit", "口播原片＋数据", "数值、趋势、因果、引语", []),
    "S08": ("企业发言与正式讲话", "真人口播与知识表达", "raven-speech-edit", "讲话录像＋原稿", "承诺、行动主体、议题、限定", []),
    "S09": ("人物访谈", "对话与多人", "raven-interview-multicam", "多机位访谈", "问答关系、说话人、金句、章节", []),
    "S10": ("视频播客与圆桌", "对话与多人", "raven-interview-multicam", "多机位或单机位多人录制", "回应关系、分歧、笑点、金句", []),
    "S11": ("课程录播", "对话与多人", "raven-course-meeting", "课堂或录屏课程", "概念、证明、案例、章节", []),
    "S12": ("会议与发布会纪要", "对话与多人", "raven-course-meeting", "会议录像", "决定、行动项、风险、未决问题", []),
    "S13": ("实拍种草与推荐", "商品与商业", "raven-commerce-story", "商品实拍＋本人讲解", "主张—证据表、使用动作、结果", []),
    "S14": ("直播带货切片", "商品与商业", "raven-commerce-story", "直播回放", "SKU 出场与返场、价格条件、演示", []),
    "S15": ("开箱与 ASMR", "商品与商业", "raven-commerce-story", "开箱实拍", "取物序列、物声、第一反应", []),
    "S16": ("品牌广告后期包装", "商品与商业", "raven-commerce-story", "品牌实拍或已生成镜头", "品牌标识、产品特写、宣言", []),
    "S17": ("本地生活探店", "商品与商业", "raven-commerce-story", "到店实拍", "地点、菜品或服务、价格、排队", []),
    "S18": ("房产与空间展示", "商品与商业", "raven-commerce-story", "空间实拍＋户型", "动线、面积、光线、适合人群", []),
    "S19": ("软件发布与功能宣传", "商品与商业", "raven-software-tutorial", "真实界面录屏", "功能、版本差异、使用场景", []),
    "S20": ("软件教程", "商品与商业", "raven-software-tutorial", "操作录屏", "步骤、点击、报错、完成状态", []),
    "S21": ("企业宣传与雇主品牌", "商品与商业", "raven-documentary-story", "企业实拍与采访", "人物、价值观、数字、工艺", []),
    "S22": ("日常 Vlog", "生活与纪实", "raven-vlog-journey", "手机日常素材", "日常动作、任务、情绪变化", []),
    "S23": ("旅行", "生活与纪实", "raven-vlog-journey", "旅行素材", "路线、地点、当地人、天气", []),
    "S24": ("美食制作", "生活与纪实", "raven-vlog-journey", "烹饪实拍", "步骤、配比、物声、成品", []),
    "S25": ("健身与运动教学", "生活与纪实", "raven-event-highlights", "训练实拍", "动作要点、计数、进步、错误动作", []),
    "S26": ("婚礼、家庭与纪念", "生活与纪实", "raven-vlog-journey", "活动与家庭素材", "仪式时刻、原声、旧照片", []),
    "S27": ("人物纪录", "生活与纪实", "raven-documentary-story", "纪实素材与采访", "人物行为、地点、档案、声音", []),
    "S28": ("新闻调查与解释", "生活与纪实", "raven-documentary-story", "采访、档案与网页证据", "主张、证据、来源、更正", []),
    "S29": ("活动、展会与演出", "生活与纪实", "raven-event-highlights", "活动多源素材", "议程、来宾、高潮、演示", []),
    "S30": ("影视解说", "娱乐与叙事后期", "raven-film-recap", "已授权影视素材", "因果、线索、人物弧、名场面", []),
    "S31": ("短剧后期包装与切条", "娱乐与叙事后期", "raven-drama-production", "已剪短剧正片", "钩子冲突、人物出场、集尾悬念", []),
    "S32": ("综艺与搞笑段子", "娱乐与叙事后期", "raven-event-highlights", "综艺或段子原片", "笑点、反应、重复梗", []),
    "S33": ("游戏高光", "娱乐与叙事后期", "raven-event-highlights", "游戏录屏", "决策、连招、经济曲线、失误", []),
    "S34": ("体育高光", "娱乐与叙事后期", "raven-event-highlights", "比赛录像", "关键回合、转折、配合、回放身份", []),
    "S35": ("音乐卡点与 MV 混剪", "娱乐与叙事后期", "raven-music-montage", "多素材＋音乐", "拍点、乐句、视觉母题、歌词", []),
    "S36": ("多平台拆条", "版本与适配", "raven-multiplatform-batch", "已有成片", "独立成立的段落、主体位置、画幅", []),
    "S37": ("本地化与双语", "版本与适配", "raven-localization", "已有成片＋字幕", "术语、文化项、画面文字、口型", []),
    "S38": ("精华版与节奏重构", "版本与适配", "raven-pacing-restructure", "已有成片", "主张链、气口、章节、音乐密度", []),
    "S39": ("参考复刻", "版本与适配", "raven-reference-style", "目标素材＋参考片", "参考的节奏、色板、构图、声画关系", []),
    "S40": ("图文与照片成片", "图文与生成补足", "raven-script-generation", "照片与文字", "地点、时间、细节、引用", []),
    "S41": ("动画讲解与数据可视化", "图文与生成补足", "raven-script-generation", "脚本或数据", "概念关系、数值、步骤、比喻", []),
    "S42": ("数字人口播", "图文与生成补足", "raven-script-generation", "脚本＋授权形象", "讲解段、演示段、对话角色", ["gen"]),
}

P = {}

P["S01"] = [
    ("kn-whiteboard", "白板图解", "speech/stepwise-teaching", "rhy-tight-explainer", "whiteboard-marker", "cap-phrase-clean", "look-clean-bright", "snd-lofi-bed", ["dia-whiteboard", "anno-arrow-point", "card-step"], "笔画顺序跟着解释走"),
    ("kn-myth-redpen", "误区红笔", "speech/myth-correction", "rhy-tight-explainer", "red-pen-review", "cap-keyword-color", "look-neutral", "snd-minimal-ticks", ["anno-strike-replace", "anno-red-pen", "anno-source-label"], "先划掉旧说法，再写正确边界"),
    ("kn-outline-build", "随讲累积提纲", "speech/progressive-outline", "rhy-chaptered", "quiet-whitespace", "cap-minimal-thin", "look-clean-bright", "snd-voice-only", ["card-checklist", "txt-fade-rise"], "旧项不消失，新项随原话加入"),
    ("kn-question-card", "问题驱动", "speech/question-answer", "rhy-hook-3s", "swiss-grid", "cap-keyword-weight", "look-neutral", "snd-minimal-ticks", ["card-question", "txt-mask-reveal"], "每段以一张问题卡开场"),
    ("kn-data-explainer", "数据讲解", "speech/evidence-led", "rhy-tight-explainer", "light-tech-board", "cap-keyword-color", "look-clean-bright", "snd-minimal-ticks", ["data-bar-chart", "data-count-up", "anno-source-label"], "每个数都带来源角标"),
    ("kn-analogy-collage", "拼贴类比", "speech/humorous-explanation", "rhy-fast-claim-first", "torn-collage", "cap-keyword-weight", "look-warm-life", "snd-statement-hits", ["comp-collage-layer", "stk-sticker-bounce", "tr-paper-tear", "sty-paper-texture"], "比喻用拼贴画出来再回到原题"),
    ("kn-expert-deep", "专业深讲", "speech/expert-deep-dive", "rhy-chaptered", "blueprint-line", "cap-phrase-clean", "look-cool-tech", "snd-voice-only", ["dia-flowchart", "anno-box-label", "card-chapter"], "线框图跟着推理一层层展开"),
    ("kn-formula", "公式推导", "speech/stepwise-teaching", "rhy-tutorial-follow", "modernist-geometry", "cap-minimal-thin", "look-neutral", "snd-voice-only", ["dia-formula", "anno-underline-draw", "bg-grid-paper"], "每步推导停在可读处"),
]
P["S02"] = [
    ("op-manifesto", "宣言大字", "speech/crisp-argument", "rhy-fast-claim-first", "manifesto-yellow", "cap-none-when-component", "look-bw-contrast", "snd-statement-hits", ["card-quote", "txt-slam"], "一句话占满一拍"),
    ("op-counterpoint", "观点与反证", "speech/counterpoint-dialogue", "rhy-chaptered", "newsroom", "cap-quote-serif", "look-neutral", "snd-voice-only", ["comp-split-screen", "card-quote", "anno-source-label"], "正反并排，反例单独成卡"),
    ("op-word-slam", "逐词冲击", "speech/crisp-argument", "rhy-fast-claim-first", "black-yellow-heavy", "cap-word-slam", "look-neutral", "snd-statement-hits", ["cam-punch-in"], "每屏 1–3 个词，主张词最大"),
    ("op-balanced", "条件式对比", "speech/balanced-comparison", "rhy-tight-explainer", "swiss-grid", "cap-keyword-color", "look-neutral", "snd-minimal-ticks", ["data-compare-split", "card-checklist"], "在什么条件下选哪个，用表格落地"),
    ("op-behind-subject", "文字穿人", "speech/constraint-pivot", "rhy-hook-3s", "acid-green-type", "cap-text-behind", "look-film-green", "snd-statement-hits", ["comp-subject-cutout", "txt-slam"], "大字从人物身后穿过"),
    ("op-editorial-column", "专栏评论", "speech/issue-context", "rhy-chaptered", "finance-journal", "cap-quote-serif", "look-grey-muted", "snd-news-bed", ["card-chapter", "card-quote", "anno-source-label"], "每个论点一页专栏版式"),
    ("op-meme-commentary", "热梗评论", "speech/humorous-explanation", "rhy-fast-claim-first", "meme-red", "cap-variety", "look-vhs-retro", "snd-variety-sfx", ["stk-reaction-burst", "cam-punch-in", "card-social-post"], "先引原帖再给反应"),
]
P["S03"] = [
    ("rv-spec-redline", "红黑参数看板", "speech/evidence-led", "rhy-tight-explainer", "redline-tech", "cap-keyword-color", "look-cool-tech", "snd-minimal-ticks", ["data-spec-table", "data-number-impact"], "只点亮正在讲的那一行"),
    ("rv-light-board", "浅色对比看板", "commerce/honest-comparison", "rhy-tight-explainer", "light-tech-board", "cap-phrase-clean", "look-product-true", "snd-minimal-ticks", ["data-compare-split", "data-bar-chart", "data-star-rating"], "同条件对比，差值用柱子说话"),
    ("rv-wireframe", "线框实物", "commerce/feature-to-action", "rhy-chaptered", "blueprint-line", "cap-keyword-color", "look-cool-tech", "snd-minimal-ticks", ["trk-object-outline", "trk-label-follow", "sty-line-sketch"], "实物转线框并跟着标注"),
    ("rv-long-term-diary", "长期使用日记", "commerce/real-use-diary", "rhy-natural", "lifestyle-pictorial", "cap-hand-note", "look-warm-life", "snd-acoustic-vlog", ["data-timeline", "card-chapter"], "按使用天数推进"),
    ("rv-limitation-first", "先说缺点", "commerce/limitation-first", "rhy-hook-3s", "red-pen-review", "cap-keyword-color", "look-neutral", "snd-voice-only", ["anno-red-pen", "card-checklist"], "开头先划掉不适合的人"),
    ("rv-unbox-setup", "开箱到上手", "commerce/setup-reality", "rhy-tutorial-follow", "swiss-grid", "cap-phrase-clean", "look-product-true", "snd-asmr-foley", ["card-step", "anno-magnifier"], "每个上手步骤都有完成画面"),
    ("rv-measurement", "测量讲清", "commerce/measurement-explained", "rhy-tight-explainer", "terminal-green", "cap-keyword-weight", "look-cool-tech", "snd-minimal-ticks", ["data-count-up", "data-line-graph", "anno-source-label"], "测量条件与读数同屏"),
]
P["S04"] = [
    ("te-stepwise", "递进教学", "speech/stepwise-teaching", "rhy-tutorial-follow", "light-tech-board", "cap-phrase-clean", "look-clean-bright", "snd-voice-only", ["card-step", "anno-arrow-point"], "每步只讲一件事并给检验方法"),
    ("te-worked-example", "例题拆解", "course-meeting/worked-example", "rhy-tutorial-follow", "paper-highlighter", "cap-keyword-color", "look-clean-bright", "snd-voice-only", ["anno-marker-highlight", "dia-formula"], "每步高亮被用到的条件"),
    ("te-misconception", "误区修复", "course-meeting/misconception-repair", "rhy-tight-explainer", "red-pen-review", "cap-keyword-weight", "look-neutral", "snd-minimal-ticks", ["anno-strike-replace"], "学生常错的那一步单独慢讲"),
    ("te-concept-ladder", "概念阶梯", "course-meeting/concept-ladder", "rhy-chaptered", "modernist-geometry", "cap-phrase-clean", "look-neutral", "snd-lofi-bed", ["dia-flowchart", "card-chapter"], "每级概念在阶梯图上点亮"),
    ("te-practice-pause", "练习暂停", "course-meeting/practice-pause", "rhy-tutorial-follow", "kraft-sticky", "cap-hand-note", "look-warm-life", "snd-lofi-bed", ["card-question", "data-progress-ring"], "讲完给倒计时让观众先想"),
    ("te-retrieval-review", "回顾速记", "course-meeting/retrieval-review", "rhy-fast-claim-first", "swiss-grid", "cap-keyword-weight", "look-clean-bright", "snd-minimal-ticks", ["card-checklist", "txt-split-flap"], "结尾一屏要点逐条翻牌"),
]
P["S05"] = [
    ("ps-reflective", "克制独白", "speech/reflective-monologue", "rhy-unhurried", "quiet-whitespace", "cap-cinema", "look-film-warm", "snd-room-tone", ["txt-blur-in"], "整片只有一次音乐进入"),
    ("ps-letter", "信件体", "speech/personal-story", "rhy-unhurried", "old-photo-album", "cap-hand-note", "look-archive-faded", "snd-acoustic-vlog", ["cam-ken-burns", "txt-handwrite"], "旧照片配手写日期"),
    ("ps-case-rebuild", "案例复盘", "speech/case-reconstruction", "rhy-chaptered", "clipping-archive", "cap-phrase-clean", "look-doc-natural", "snd-voice-only", ["data-timeline", "anno-circle-callout"], "时间线上圈出那次关键选择"),
    ("ps-companion", "自然陪伴", "speech/conversational-company", "rhy-natural", "paper-highlighter", "cap-hand-note", "look-soft-skin", "snd-lofi-bed", ["anno-marker-highlight"], "只划一处最想让你记住的话"),
    ("ps-mono-portrait", "黑白人物", "speech/personal-story", "rhy-chaptered", "mono-portrait", "cap-quote-serif", "look-mono-subject", "snd-ambience", ["card-chapter", "comp-mono-keep-subject"], "黑白中只有人保留原色"),
    ("ps-handpaint-memory", "回忆转绘", "speech/personal-story", "rhy-unhurried", "lifestyle-pictorial", "cap-minimal-thin", "look-pastel-book", "snd-acoustic-vlog", ["sty-handpaint-window", "comp-split-screen"], "讲到回忆时实拍转为手绘"),
]
P["S06"] = [
    ("nb-newsroom", "新闻条带", "documentary/fact-brief", "rhy-news-brisk", "newsroom", "cap-news-lower", "look-neutral", "snd-news-bed", ["card-ticker", "anno-source-label", "card-lower-third"], "每条一句标题加来源"),
    ("nb-daily-digest", "每日要点", "documentary/ongoing-snapshot", "rhy-news-brisk", "swiss-grid", "cap-keyword-weight", "look-clean-bright", "snd-news-bed", ["txt-split-flap", "card-checklist", "tr-push-slide"], "开头翻牌列出今日三件事"),
    ("nb-change-since", "更新对比", "documentary/change-since-update", "rhy-tight-explainer", "light-tech-board", "cap-keyword-color", "look-neutral", "snd-minimal-ticks", ["data-compare-split", "anno-strike-replace"], "上次的数字被新数字划掉"),
    ("nb-map-dispatch", "地图快讯", "documentary/field-dispatch", "rhy-news-brisk", "blueprint-line", "cap-doc-caption", "look-doc-natural", "snd-news-bed", ["data-map-route", "card-lower-third"], "每条先在地图上落点"),
    ("nb-known-unknown", "已知与未知", "documentary/known-unknown", "rhy-chaptered", "finance-journal", "cap-phrase-clean", "look-grey-muted", "snd-voice-only", ["card-checklist", "anno-box-label"], "已确认与待确认分两栏"),
    ("nb-vertical-flash", "竖屏快讯", "documentary/consequences", "rhy-hook-3s", "deep-blue-impact", "cap-word-slam", "look-clean-bright", "snd-statement-hits", ["data-number-impact", "card-title"], "一个数字定开头"),
]
P["S07"] = [
    ("fi-journal", "财经报刊", "speech/evidence-led", "rhy-chaptered", "finance-journal", "cap-quote-serif", "look-grey-muted", "snd-news-bed", ["data-line-graph", "card-quote", "anno-source-label"], "数据页与引语页交替"),
    ("fi-impact-numbers", "大数冲击", "speech/crisp-argument", "rhy-fast-claim-first", "deep-blue-impact", "cap-none-when-component", "look-cool-tech", "snd-statement-hits", ["data-number-impact", "data-bar-race"], "关键数字占满一拍"),
    ("fi-cause-chain", "因果链条", "speech/expert-deep-dive", "rhy-tight-explainer", "blueprint-line", "cap-phrase-clean", "look-cool-tech", "snd-lofi-bed", ["dia-cause-map", "data-count-up"], "一张因果图贯穿全片"),
    ("fi-archive-collage", "档案拼贴讲解", "documentary/mechanism-explainer", "rhy-hook-3s", "clipping-archive", "cap-keyword-color", "look-archive-faded", "snd-news-bed", ["comp-collage-layer", "cam-ken-burns", "tr-paper-tear"], "史料剪报拼出来龙去脉"),
    ("fi-executive-brief", "决策简报", "speech/executive-brief", "rhy-tight-explainer", "blue-professional", "cap-phrase-clean", "look-neutral", "snd-voice-only", ["card-checklist", "data-donut"], "结论、依据、下一步三页"),
    ("fi-chart-race", "排名竞赛", "speech/balanced-comparison", "rhy-montage-build", "dark-liquid", "cap-keyword-weight", "look-cool-tech", "snd-beat-driven", ["data-bar-race", "data-timeline"], "排名变化跟着讲述推进"),
]
P["S08"] = [
    ("ex-complete-record", "完整留档", "speech/complete-record", "rhy-natural", "blue-professional", "cap-phrase-clean", "look-neutral", "snd-room-tone", ["card-lower-third"], "不剪掉任何限定与承诺"),
    ("ex-actor-action", "行动清单", "speech/actor-action", "rhy-tight-explainer", "swiss-grid", "cap-keyword-color", "look-neutral", "snd-voice-only", ["card-checklist", "card-lower-third"], "谁要做什么逐条列出"),
    ("ex-issue-brief", "议题专题", "speech/issue-context", "rhy-chaptered", "newsroom", "cap-quote-serif", "look-grey-muted", "snd-news-bed", ["card-chapter", "card-quote"], "每个议题一页原话"),
    ("ex-premium-keynote", "发布会高端", "speech/crisp-argument", "rhy-hook-3s", "black-gold-premium", "cap-minimal-thin", "look-black-gold", "snd-corporate-uplift", ["card-title", "data-number-impact", "card-logo-sting"], "黑场中一个数字亮起"),
    ("ex-warm-allhands", "内部温暖版", "speech/conversational-company", "rhy-natural", "warm-orange-geo", "cap-phrase-clean", "look-warm-life", "snd-acoustic-vlog", ["card-lower-third", "fx-confetti"], "彩纸只给真正的里程碑"),
    ("ex-bilingual-global", "双语对外", "localization/attributed-argument", "rhy-natural", "blue-professional", "cap-bilingual-stack", "look-neutral", "snd-room-tone", ["card-lower-third"], "术语首现给原文"),
]
P["S09"] = [
    ("iv-portrait", "人物肖像", "interview/reflective-portrait", "rhy-unhurried", "mono-portrait", "cap-cinema", "look-bw-contrast", "snd-room-tone", ["card-lower-third", "card-chapter"], "每章前一张静止人物页"),
    ("iv-oral-history", "口述历史", "interview/oral-history", "rhy-observational", "old-photo-album", "cap-doc-caption", "look-archive-faded", "snd-room-tone", ["cam-ken-burns", "data-timeline"], "原话与老照片交替"),
    ("iv-idea-duel", "观点交锋", "interview/idea-duel", "rhy-fast-claim-first", "deep-blue-impact", "cap-speaker-color", "look-neutral", "snd-statement-hits", ["comp-split-screen", "card-quote"], "分屏对峙，金句单独上卡"),
    ("iv-practitioner", "实践案例", "interview/practitioner-case", "rhy-chaptered", "light-tech-board", "cap-phrase-clean", "look-clean-bright", "snd-lofi-bed", ["card-step", "anno-box-label"], "问题、做法、结果三段"),
    ("iv-short-answers", "短答卡", "interview/short-answer-card", "rhy-hook-3s", "swiss-grid", "cap-keyword-weight", "look-clean-bright", "snd-minimal-ticks", ["card-question", "txt-mask-reveal"], "一个问题一张卡一个回答"),
    ("iv-place", "场所沉浸", "interview/place-immersive", "rhy-observational", "lifestyle-pictorial", "cap-minimal-thin", "look-doc-natural", "snd-ambience", ["card-lower-third"], "受访者的空间先于受访者出现"),
    ("iv-technical", "技术深谈", "interview/technical-deep-dive", "rhy-chaptered", "blueprint-line", "cap-keyword-color", "look-cool-tech", "snd-voice-only", ["dia-flowchart", "anno-box-label"], "关键概念随对话画成图"),
]
P["S10"] = [
    ("pc-roundtable-map", "圆桌地图", "interview/roundtable-map", "rhy-natural", "warm-orange-geo", "cap-speaker-color", "look-warm-life", "snd-room-tone", ["card-lower-third", "dia-flowchart"], "谁回应了谁用连线标出"),
    ("pc-audiogram", "声波卡片", "interview/short-answer-card", "rhy-hook-3s", "soft-organic-gradient", "cap-karaoke", "look-neutral", "snd-voice-only", ["av-waveform", "card-quote", "bg-gradient-mesh"], "竖屏声波加逐词字幕"),
    ("pc-comic-timing", "喜剧节奏", "interview/comic-timing", "rhy-fast-claim-first", "retro-pop", "cap-word-pop", "look-high-key-summer", "snd-variety-sfx", ["stk-reaction-burst", "cam-punch-in"], "笑点前留半拍再推近"),
    ("pc-disagreement", "分歧保留", "interview/disagreement-preserved", "rhy-chaptered", "newsroom", "cap-speaker-color", "look-grey-muted", "snd-voice-only", ["comp-split-screen", "card-checklist"], "分歧点不被剪成共识"),
    ("pc-contemplative", "沉思对话", "interview/contemplative-dialogue", "rhy-observational", "quiet-whitespace", "cap-minimal-thin", "look-winter-blue", "snd-ambience", [], "长镜头不切换机位"),
    ("pc-clip-card", "金句切片", "multiplatform/claim-proof", "rhy-live-slice", "manifesto-yellow", "cap-pill-karaoke", "look-clean-bright", "snd-statement-hits", ["card-quote", "card-cta-end"], "金句后紧跟它的依据"),
]
P["S11"] = [
    ("co-lab-demo", "实验演示", "course-meeting/lab-demonstration", "rhy-tutorial-follow", "light-tech-board", "cap-phrase-clean", "look-clean-bright", "snd-voice-only", ["anno-magnifier", "card-step"], "关键操作局部放大"),
    ("co-proof-chain", "证明链", "course-meeting/proof-chain", "rhy-chaptered", "quiet-whitespace", "cap-minimal-thin", "look-neutral", "snd-voice-only", ["dia-formula", "anno-underline-draw"], "每步推导标出依据"),
    ("co-historical", "历史发展", "course-meeting/historical-development", "rhy-chaptered", "clipping-archive", "cap-doc-caption", "look-archive-faded", "snd-room-tone", ["data-timeline", "cam-ken-burns"], "时间轴上逐段点亮"),
    ("co-case-autopsy", "案例剖析", "course-meeting/case-autopsy", "rhy-tight-explainer", "red-pen-review", "cap-keyword-color", "look-neutral", "snd-minimal-ticks", ["anno-circle-callout", "dia-cause-map"], "红笔圈出失败的那一环"),
    ("co-contrast-pair", "对照组", "course-meeting/contrast-pair", "rhy-tight-explainer", "swiss-grid", "cap-keyword-weight", "look-clean-bright", "snd-minimal-ticks", ["data-compare-split"], "两个例子只差一个变量"),
    ("co-chapter-index", "章节索引", "course-meeting/process-map", "rhy-chaptered", "modernist-geometry", "cap-phrase-clean", "look-neutral", "snd-lofi-bed", ["card-chapter", "dia-flowchart", "data-progress-ring"], "进度环告诉学生学到哪"),
]
P["S12"] = [
    ("mt-decision-trace", "决策追踪", "course-meeting/decision-trace", "rhy-tight-explainer", "blue-professional", "cap-speaker-color", "look-neutral", "snd-voice-only", ["card-checklist", "data-timeline"], "每个决定标出提出人和时间点"),
    ("mt-action-handoff", "行动交接", "course-meeting/action-handoff", "rhy-news-brisk", "swiss-grid", "cap-keyword-color", "look-neutral", "snd-minimal-ticks", ["card-checklist", "card-lower-third"], "结尾一屏谁在何时做什么"),
    ("mt-risk-register", "风险登记", "course-meeting/risk-register", "rhy-chaptered", "redline-tech", "cap-phrase-clean", "look-cool-tech", "snd-voice-only", ["data-spec-table", "anno-box-label"], "风险表逐行点亮"),
    ("mt-launch-recap", "发布会回顾", "speech/crisp-argument", "rhy-hook-3s", "dark-liquid", "cap-keyword-weight", "look-black-gold", "snd-corporate-uplift", ["data-number-impact", "card-title", "card-logo-sting"], "三个发布数字依次亮起"),
    ("mt-open-questions", "未决问题", "course-meeting/open-question-ledger", "rhy-chaptered", "kraft-sticky", "cap-hand-note", "look-warm-life", "snd-voice-only", ["card-question", "card-checklist"], "便签墙上留着未解决的问题"),
    ("mt-disagreement", "分歧线索", "course-meeting/disagreement-thread", "rhy-tight-explainer", "newsroom", "cap-speaker-color", "look-grey-muted", "snd-voice-only", ["comp-split-screen", "card-quote"], "反对意见原话完整保留"),
]
P["S13"] = [
    ("pr-action-proof", "操作作证", "commerce/action-proof", "rhy-tight-explainer", "swiss-grid", "cap-phrase-clean", "look-product-true", "snd-ambience", ["anno-box-label", "data-count-up"], "计时器只出现在证明镜头上"),
    ("pr-quiet-reco", "安静推荐", "commerce/quiet-recommendation", "rhy-natural", "lifestyle-pictorial", "cap-hand-note", "look-warm-life", "snd-lofi-bed", ["anno-marker-highlight"], "只说一个真实理由"),
    ("pr-one-friction", "一个麻烦", "commerce/one-friction", "rhy-hook-3s", "warm-orange-geo", "cap-keyword-weight", "look-clean-bright", "snd-minimal-ticks", ["card-question", "anno-arrow-point"], "开头复现那个具体麻烦"),
    ("pr-result-first", "结果先行", "commerce/result-first", "rhy-hook-3s", "glassmorph", "cap-keyword-color", "look-clean-bright", "snd-statement-hits", ["comp-split-screen", "tr-wipe"], "先看结果再倒回过程"),
    ("pr-honest-compare", "条件对比", "commerce/honest-comparison", "rhy-tight-explainer", "modernist-geometry", "cap-keyword-color", "look-product-true", "snd-minimal-ticks", ["data-compare-split", "data-star-rating", "card-testimonial"], "同条件左右并排"),
    ("pr-skeptic", "从怀疑到决定", "commerce/skeptic-to-decision", "rhy-chaptered", "red-pen-review", "cap-keyword-color", "look-neutral", "snd-voice-only", ["anno-strike-replace", "card-checklist"], "疑问一条条被划掉或保留"),
    ("pr-routine-fit", "融入日常", "commerce/routine-integration", "rhy-natural", "paper-highlighter", "cap-hand-note", "look-airy", "snd-acoustic-vlog", ["data-timeline"], "一天里它出现的三个时刻"),
    ("pr-outfit-choices", "穿搭选择", "commerce/outfit-choices", "rhy-beat-sync", "retro-pop", "cap-word-pop", "look-high-key-summer", "snd-beat-driven", ["comp-split-screen", "av-beat-freeze"], "每个卡点换一套"),
]
P["S14"] = [
    ("ls-single-sku", "单品证据切片", "commerce/offer-with-context", "rhy-live-slice", "light-tech-board", "cap-keyword-color", "look-product-true", "snd-voice-only", ["data-price-tag", "anno-box-label"], "价格条件与有效期同屏"),
    ("ls-demo-first", "演示开头", "commerce/action-proof", "rhy-hook-3s", "black-yellow-heavy", "cap-pill-karaoke", "look-product-true", "snd-statement-hits", ["anno-magnifier", "data-price-tag"], "第一秒就是演示结果"),
    ("ls-qa-reply", "弹幕答疑", "commerce/comment-response", "rhy-live-slice", "anime-danmaku", "cap-danmaku", "look-clean-bright", "snd-minimal-ticks", ["card-social-post", "card-question"], "先上观众问题再给原话回答"),
    ("ls-host-personality", "主播人设", "highlights/live-personality", "rhy-fast-claim-first", "cute-sticker", "cap-emoji-accent", "look-clean-bright", "snd-variety-sfx", ["stk-reaction-burst", "cam-punch-in"], "只保留主播真实反应"),
    ("ls-measure-proof", "实测数据", "commerce/measurement-explained", "rhy-tight-explainer", "redline-tech", "cap-keyword-weight", "look-product-true", "snd-minimal-ticks", ["data-spec-table", "data-count-up"], "实测读数逐行点亮"),
    ("ls-calm-explainer", "冷静讲解版", "commerce/small-specific-claim", "rhy-natural", "quiet-whitespace", "cap-phrase-clean", "look-neutral", "snd-voice-only", ["anno-source-label"], "一个可证实的小主张"),
]
P["S15"] = [
    ("ub-window-asmr", "窗边 ASMR", "commerce/object-sound", "rhy-observational", "quiet-whitespace", "cap-minimal-thin", "look-airy", "snd-asmr-foley", [], "全片无旁白，只有开盒声"),
    ("ub-packing-list", "内容清点", "commerce/packing-contents", "rhy-tight-explainer", "swiss-grid", "cap-keyword-color", "look-product-true", "snd-asmr-foley", ["card-checklist", "anno-box-label"], "每取出一件就在清单上打勾"),
    ("ub-first-impression", "第一印象", "commerce/first-impression", "rhy-natural", "lifestyle-pictorial", "cap-hand-note", "look-warm-life", "snd-ambience", ["anno-marker-highlight"], "保留第一次拿起时的原话"),
    ("ub-unbox-to-use", "开箱到使用", "commerce/unbox-to-use", "rhy-tutorial-follow", "light-tech-board", "cap-phrase-clean", "look-clean-bright", "snd-minimal-ticks", ["card-step", "anno-magnifier"], "开箱和第一次使用连成一序列"),
    ("ub-hands-only", "只有手", "commerce/hands-only-use", "rhy-observational", "neo-chinese-minimal", "cap-vertical", "look-morandi", "snd-asmr-foley", [], "画面里只有手和物"),
    ("ub-mystery-reveal", "盲盒揭晓", "commerce/sensory-reaction", "rhy-hook-3s", "cute-sticker", "cap-word-pop", "look-high-key-summer", "snd-variety-sfx", ["stk-emoji-pop", "fx-confetti", "fx-sparkle"], "延迟露出，反应先于商品"),
]
P["S16"] = [
    ("bd-black-gold", "黑金质感", "commerce/brand-observation", "rhy-trailer", "black-gold-premium", "cap-minimal-thin", "look-black-gold", "snd-cinematic-swell", ["card-logo-sting", "txt-gloss-sweep"], "光沿产品边缘走一次"),
    ("bd-manifesto", "品牌宣言", "commerce/declared-manifesto", "rhy-fast-claim-first", "manifesto-yellow", "cap-word-slam", "look-bw-contrast", "snd-statement-hits", ["txt-slam", "card-logo-sting"], "宣言词逐词砸在黑白画面上"),
    ("bd-craft-process", "工艺过程", "commerce/craft-decisions", "rhy-observational", "lifestyle-pictorial", "cap-doc-caption", "look-film-warm", "snd-asmr-foley", ["card-lower-third", "anno-source-label"], "每道工序一次手部特写"),
    ("bd-material-journey", "材料之旅", "commerce/material-journey", "rhy-montage-build", "azure-landscape", "cap-vertical", "look-doc-natural", "snd-ambience", ["data-map-route", "tr-ink-bleed"], "原料产地到成品的地图路线"),
    ("bd-founder", "创始人的选择", "commerce/founder-choice", "rhy-chaptered", "mono-portrait", "cap-quote-serif", "look-bw-contrast", "snd-room-tone", ["card-quote", "card-chapter"], "一个艰难决定讲透"),
    ("bd-pop-campaign", "波普活动", "commerce/product-in-culture", "rhy-beat-sync", "retro-pop", "cap-variety", "look-high-key-summer", "snd-beat-driven", ["stk-sticker-bounce", "tr-shape-iris", "av-beat-pulse"], "形状转场跟拍点"),
    ("bd-neo-chinese", "国潮新品", "commerce/archive-and-now", "rhy-trailer", "vermilion-gold", "cap-vertical", "look-film-warm", "snd-cinematic-swell", ["txt-calligraphy-title", "tr-ink-bleed", "card-logo-sting"], "书法题字落版"),
]
P["S17"] = [
    ("ll-place-people", "店与人", "commerce/place-and-people", "rhy-natural", "lifestyle-pictorial", "cap-hand-note", "look-warm-life", "snd-ambience", ["card-lower-third", "data-map-route"], "先拍门口再拍人"),
    ("ll-signature-dish", "招牌菜", "commerce/sensory-reaction", "rhy-beat-sync", "variety-color-caption", "cap-keyword-weight", "look-food-rich", "snd-asmr-foley", ["data-price-tag", "cam-punch-in"], "第一口的声音放大"),
    ("ll-honest-visit", "真实到店", "commerce/experience-with-caveat", "rhy-chaptered", "kraft-sticky", "cap-hand-note", "look-doc-natural", "snd-ambience", ["data-star-rating", "card-checklist"], "优点和排队时长一起说"),
    ("ll-service-moment", "服务瞬间", "commerce/service-moment", "rhy-observational", "quiet-whitespace", "cap-minimal-thin", "look-film-warm", "snd-room-tone", [], "只拍一次服务的完整过程"),
    ("ll-route-guide", "路线攻略", "vlog-journey/route-with-evidence", "rhy-tight-explainer", "warm-orange-geo", "cap-keyword-color", "look-high-key-summer", "snd-acoustic-vlog", ["data-map-route", "card-step", "data-price-tag"], "路线、价格、时间三件套"),
    ("ll-night-market", "夜市氛围", "vlog-journey/sensory-fragments", "rhy-montage-build", "neon-night-board", "cap-neon-glow", "look-night-clean", "snd-ambience", ["fx-glow-bloom"], "灯牌是唯一的光源"),
]
P["S18"] = [
    ("re-space-walk", "空间漫游", "vlog-journey/space-discovery", "rhy-observational", "quiet-whitespace", "cap-minimal-thin", "look-clean-bright", "snd-ambience", ["anno-box-label"], "一镜走完动线"),
    ("re-floorplan", "户型标注", "commerce/detail-and-whole", "rhy-tight-explainer", "blueprint-line", "cap-keyword-color", "look-clean-bright", "snd-minimal-ticks", ["anno-box-label", "data-spec-table"], "户型图与实景交替"),
    ("re-lifestyle", "生活方式", "commerce/routine-integration", "rhy-natural", "neo-chinese-minimal", "cap-hand-note", "look-morandi", "snd-acoustic-vlog", ["txt-fade-rise"], "一天的光线在房间里移动"),
    ("re-before-after", "改造前后", "commerce/honest-improvement", "rhy-hook-3s", "glassmorph", "cap-keyword-weight", "look-clean-bright", "snd-statement-hits", ["data-compare-split", "tr-wipe"], "同机位前后擦除"),
    ("re-premium", "高端楼盘", "commerce/brand-observation", "rhy-trailer", "black-gold-premium", "cap-minimal-thin", "look-golden-hour", "snd-cinematic-swell", ["card-title", "txt-gloss-sweep"], "黄金时刻的外立面"),
    ("re-condition-led", "适合谁", "commerce/condition-led", "rhy-chaptered", "swiss-grid", "cap-phrase-clean", "look-neutral", "snd-voice-only", ["card-checklist", "data-spec-table"], "先说适合哪类家庭"),
]
P["S19"] = [
    ("ap-device-showcase", "设备样机", "software/evidence-demo", "rhy-hook-3s", "glassmorph", "cap-keyword-weight", "look-clean-bright", "snd-corporate-uplift", ["comp-device-frame", "scr-cursor-zoom", "card-cta-end"], "真实界面放进样机"),
    ("ap-release-delta", "版本变化", "software/release-delta", "rhy-tight-explainer", "light-tech-board", "cap-phrase-clean", "look-neutral", "snd-minimal-ticks", ["data-compare-split", "scr-click-ripple"], "新旧界面同位对照"),
    ("ap-code-diff", "开发者变更", "software/expert-shortcut", "rhy-tight-explainer", "terminal-green", "cap-minimal-thin", "look-cool-tech", "snd-minimal-ticks", ["scr-code-diff", "scr-code-typing", "scr-keystroke"], "代码差异逐行亮起"),
    ("ap-kinetic-promo", "动感宣传", "software/progressive-reveal", "rhy-beat-sync", "dark-liquid", "cap-word-slam", "look-cool-tech", "snd-beat-driven", ["txt-scramble-decode", "tr-zoom-through", "card-notification", "txt-variable-weight"], "功能名乱码解码而出"),
    ("ap-problem-story", "问题故事", "software/case-story", "rhy-chaptered", "warm-orange-geo", "cap-keyword-color", "look-warm-life", "snd-acoustic-vlog", ["card-chat-thread", "scr-cursor-zoom"], "从一条真实求助消息开始"),
    ("ap-3d-hero", "3D 主视觉", "software/before-after", "rhy-trailer", "holo-scifi", "cap-minimal-thin", "look-neon-cyber", "snd-cinematic-swell", ["txt-3d-extrude", "comp-device-frame"], "界面卡片在空间里展开"),
]
P["S20"] = [
    ("tu-first-run", "首次上手", "software/guided-first-run", "rhy-tutorial-follow", "light-tech-board", "cap-phrase-clean", "look-clean-bright", "snd-voice-only", ["scr-cursor-zoom", "scr-click-ripple", "card-step"], "每次点击前光标先停一下"),
    ("tu-silent", "无声演示", "software/silent-walkthrough", "rhy-tutorial-follow", "swiss-grid", "cap-keyword-color", "look-neutral", "snd-lofi-bed", ["scr-keystroke", "card-step"], "按键提示代替旁白"),
    ("tu-diagnose", "排错修复", "software/diagnose-repair", "rhy-tight-explainer", "red-pen-review", "cap-keyword-color", "look-neutral", "snd-minimal-ticks", ["anno-circle-callout", "scr-cursor-zoom"], "报错处红圈，修复后对勾"),
    ("tu-keyboard", "快捷键高手", "software/keyboard-workflow", "rhy-fast-claim-first", "terminal-green", "cap-minimal-thin", "look-cool-tech", "snd-retro-game", ["scr-keystroke", "scr-code-typing"], "每个快捷键一次按键提示"),
    ("tu-before-after", "效果对比", "software/before-after", "rhy-hook-3s", "glassmorph", "cap-keyword-weight", "look-clean-bright", "snd-statement-hits", ["comp-split-screen", "tr-wipe"], "先看最终效果"),
    ("tu-concept-action", "概念到操作", "software/concept-action", "rhy-chaptered", "whiteboard-marker", "cap-phrase-clean", "look-clean-bright", "snd-voice-only", ["dia-whiteboard", "scr-cursor-zoom"], "先画原理再进软件"),
]
P["S21"] = [
    ("cp-workers", "普通员工", "commerce/ordinary-workers", "rhy-observational", "lifestyle-pictorial", "cap-doc-caption", "look-doc-natural", "snd-room-tone", ["card-lower-third"], "每个人只拍他手上的活"),
    ("cp-values", "价值观在行动", "commerce/values-in-action", "rhy-chaptered", "blue-professional", "cap-phrase-clean", "look-clean-bright", "snd-corporate-uplift", ["card-chapter", "data-number-impact"], "一个价值观对应一个真实动作"),
    ("cp-annual-numbers", "年度数字", "speech/evidence-led", "rhy-montage-build", "deep-blue-impact", "cap-word-slam", "look-cool-tech", "snd-beat-driven", ["data-count-up", "data-number-impact", "data-bar-chart"], "数字按节拍滚动"),
    ("cp-recruit", "招聘活力", "commerce/community-relationship", "rhy-beat-sync", "warm-orange-geo", "cap-word-pop", "look-high-key-summer", "snd-beat-driven", ["card-lower-third", "stk-sticker-bounce", "card-cta-end"], "每个工位一个卡点"),
    ("cp-premium", "高端形象", "commerce/brand-process-without-hero", "rhy-trailer", "black-gold-premium", "cap-minimal-thin", "look-black-gold", "snd-cinematic-swell", ["card-logo-sting", "txt-gloss-sweep"], "不出现英雄人物，只有过程"),
    ("cp-health", "医疗健康", "commerce/condition-led", "rhy-natural", "health-fresh", "cap-phrase-clean", "look-clean-bright", "snd-corporate-uplift", ["card-checklist", "anno-source-label"], "每条健康主张都有来源"),
]
P["S22"] = [
    ("vd-ritual", "日常仪式", "vlog-journey/ordinary-ritual", "rhy-natural", "paper-highlighter", "cap-hand-note", "look-warm-life", "snd-acoustic-vlog", ["txt-handwrite"], "同一个动作每天出现一次"),
    ("vd-small-mission", "小任务", "vlog-journey/small-mission", "rhy-hook-3s", "cute-sticker", "cap-word-pop", "look-airy", "snd-variety-sfx", ["card-checklist", "stk-emoji-pop"], "开头立任务，结尾打勾"),
    ("vd-quiet-company", "安静陪伴", "vlog-journey/quiet-company", "rhy-observational", "quiet-whitespace", "cap-minimal-thin", "look-winter-blue", "snd-ambience", [], "不说话的十分钟"),
    ("vd-film-diary", "胶片日记", "vlog-journey/day-texture", "rhy-montage-build", "film-leader-card", "cap-cinema", "look-film-warm", "snd-acoustic-vlog", ["sty-film-grain", "tr-light-leak", "tr-film-burn"], "每段以片孔字卡开头"),
    ("vd-expectation", "预期与现实", "vlog-journey/expectation-reality", "rhy-fast-claim-first", "retro-pop", "cap-keyword-weight", "look-high-key-summer", "snd-variety-sfx", ["comp-split-screen", "stk-reaction-burst"], "预期画面和现实分屏"),
    ("vd-process-notebook", "过程手账", "vlog-journey/process-notebook", "rhy-tutorial-follow", "kraft-sticky", "cap-hand-note", "look-morandi", "snd-lofi-bed", ["card-step", "anno-circle-callout"], "每一步贴一张便签"),
]
P["S23"] = [
    ("tv-route", "路线有据", "vlog-journey/route-with-evidence", "rhy-tight-explainer", "modernist-geometry", "cap-keyword-color", "look-high-key-summer", "snd-acoustic-vlog", ["data-map-route", "card-lower-third"], "红线路线随行程画出"),
    ("tv-one-place", "一地久留", "vlog-journey/one-place-stay", "rhy-observational", "quiet-whitespace", "cap-vertical", "look-film-green", "snd-ambience", [], "同一个窗口的早中晚"),
    ("tv-paper-atlas", "纸上地图", "vlog-journey/space-discovery", "rhy-chaptered", "torn-collage", "cap-hand-note", "look-warm-life", "snd-acoustic-vlog", ["data-map-route", "comp-collage-layer"], "剪纸地图上贴照片"),
    ("tv-local", "当地人", "vlog-journey/local-encounter", "rhy-natural", "lifestyle-pictorial", "cap-bilingual-stack", "look-doc-natural", "snd-ambience", ["card-lower-third"], "当地人的原话加双语"),
    ("tv-landscape", "风景尺度", "vlog-journey/landscape-human-scale", "rhy-beat-sync", "azure-landscape", "cap-minimal-thin", "look-golden-hour", "snd-beat-driven", ["tr-zoom-through", "cam-speed-ramp"], "人始终在画面里作尺度"),
    ("tv-weather", "天气作角色", "vlog-journey/weather-as-character", "rhy-observational", "ink-xuan", "cap-vertical", "look-winter-blue", "snd-ambience", ["tr-ink-bleed"], "雨的声音串起每一段"),
]
P["S24"] = [
    ("fd-recipe", "跟做菜谱", "vlog-journey/process-notebook", "rhy-tutorial-follow", "warm-orange-geo", "cap-keyword-color", "look-food-rich", "snd-asmr-foley", ["card-step", "data-count-up"], "每步给出克数和时间"),
    ("fd-asmr-cook", "无声烹饪", "commerce/object-sound", "rhy-observational", "neo-chinese-minimal", "cap-vertical", "look-food-rich", "snd-asmr-foley", [], "只有刀与锅的声音"),
    ("fd-street", "街头烟火", "vlog-journey/sensory-fragments", "rhy-beat-sync", "variety-color-caption", "cap-variety", "look-hk-night", "snd-beat-driven", ["cam-punch-in", "stk-reaction-burst"], "出锅瞬间卡点"),
    ("fd-family-recipe", "家传味道", "vlog-journey/family-keepsake", "rhy-unhurried", "old-photo-album", "cap-hand-note", "look-film-warm", "snd-acoustic-vlog", ["cam-ken-burns", "txt-handwrite"], "老照片里的同一道菜"),
    ("fd-nutrition", "轻食数据", "commerce/measurement-explained", "rhy-tight-explainer", "health-fresh", "cap-keyword-weight", "look-clean-bright", "snd-minimal-ticks", ["data-donut", "data-number-impact"], "热量与营养用环形图"),
    ("fd-fail-retry", "翻车再来", "commerce/mistake-and-learning", "rhy-fast-claim-first", "meme-red", "cap-word-pop", "look-vhs-retro", "snd-variety-sfx", ["stk-reaction-burst", "cam-freeze-frame"], "翻车瞬间定格"),
]
P["S25"] = [
    ("ft-form", "动作拆解", "highlights/technique-breakdown", "rhy-tutorial-follow", "light-tech-board", "cap-keyword-color", "look-clean-bright", "snd-voice-only", ["anno-arrow-point", "cam-freeze-frame", "anno-magnifier"], "关键角度定格加箭头"),
    ("ft-workout-beat", "跟练节拍", "highlights/training-progress", "rhy-beat-sync", "esports-hud", "cap-word-slam", "look-high-key-summer", "snd-beat-driven", ["data-progress-ring", "data-count-up"], "倒计时环跟着拍点走"),
    ("ft-progress", "进步日记", "vlog-journey/before-after-context", "rhy-montage-build", "swiss-grid", "cap-phrase-clean", "look-neutral", "snd-acoustic-vlog", ["data-line-graph", "comp-split-screen"], "同角度第 1 天与第 90 天"),
    ("ft-correction", "错误动作纠正", "course-meeting/misconception-repair", "rhy-tight-explainer", "red-pen-review", "cap-keyword-color", "look-clean-bright", "snd-voice-only", ["anno-red-pen", "comp-split-screen"], "错误与正确同屏并排"),
    ("ft-outdoor-film", "户外胶片", "highlights/moment-replay", "rhy-highlight-burst", "film-leader-card", "cap-cinema", "look-film-green", "snd-cinematic-swell", ["cam-speed-ramp", "sty-film-grain"], "落地前一刻变速"),
    ("ft-calm-yoga", "舒缓瑜伽", "vlog-journey/quiet-company", "rhy-unhurried", "soft-organic-gradient", "cap-minimal-thin", "look-airy", "snd-lofi-bed", ["data-progress-ring", "bg-aurora"], "呼吸计数代替口令"),
]
P["S26"] = [
    ("fe-golden-wedding", "黄金时刻婚礼", "vlog-journey/collective-moment", "rhy-montage-build", "lifestyle-pictorial", "cap-cinema", "look-golden-hour", "snd-cinematic-swell", ["card-title", "tr-light-leak", "fx-light-leak"], "誓词原声压过音乐"),
    ("fe-keepsake", "家庭纪念", "vlog-journey/family-keepsake", "rhy-unhurried", "old-photo-album", "cap-hand-note", "look-archive-faded", "snd-acoustic-vlog", ["cam-ken-burns", "cam-parallax-25d"], "老照片 2.5D 动起来"),
    ("fe-kid-growth", "成长记录", "vlog-journey/time-return", "rhy-montage-build", "cute-sticker", "cap-word-pop", "look-pastel-book", "snd-acoustic-vlog", ["data-timeline", "stk-sticker-bounce"], "同一个门框的身高线"),
    ("fe-party", "派对高能", "vlog-journey/event-experience", "rhy-beat-sync", "retro-pop", "cap-variety", "look-high-key-summer", "snd-beat-driven", ["fx-confetti", "av-beat-pulse"], "干杯时彩纸只出现一次"),
    ("fe-letter", "写给你的信", "vlog-journey/memory-letter", "rhy-unhurried", "kraft-sticky", "cap-hand-note", "look-film-warm", "snd-room-tone", ["txt-handwrite"], "手写信逐字出现"),
    ("fe-mono-classic", "黑白经典", "vlog-journey/shared-detail", "rhy-observational", "silent-intertitle", "cap-cinema", "look-bw-contrast", "snd-room-tone", ["card-chapter"], "默片字卡分章"),
]
P["S27"] = [
    ("dc-observational", "观察式", "documentary/observational-sequence", "rhy-observational", "quiet-whitespace", "cap-doc-caption", "look-doc-natural", "snd-ambience", [], "不加任何图形"),
    ("dc-hands-craft", "手艺", "documentary/hands-craft", "rhy-observational", "neo-chinese-minimal", "cap-vertical", "look-film-warm", "snd-asmr-foley", ["card-lower-third", "cam-rack-focus"], "每个手艺动作完整保留"),
    ("dc-archive-present", "档案与现在", "documentary/archive-present", "rhy-chaptered", "clipping-archive", "cap-doc-caption", "look-archive-faded", "snd-room-tone", ["cam-ken-burns", "comp-split-screen"], "同一地点今昔分屏"),
    ("dc-voice-led", "声音主导", "documentary/voice-led", "rhy-unhurried", "mono-portrait", "cap-cinema", "look-bw-contrast", "snd-room-tone", ["card-quote"], "黑场中先听到声音"),
    ("dc-collective", "群像", "documentary/collective-portrait", "rhy-montage-build", "lifestyle-pictorial", "cap-doc-caption", "look-doc-natural", "snd-ambience", ["card-lower-third", "comp-split-screen"], "九宫格群像收尾"),
    ("dc-workday", "一天的工作", "documentary/workday", "rhy-chaptered", "swiss-grid", "cap-doc-caption", "look-neutral", "snd-ambience", ["data-timeline", "card-lower-third"], "时钟时间作章节"),
]
P["S28"] = [
    ("ni-trail", "调查线索", "documentary/investigative-trail", "rhy-chaptered", "clipping-archive", "cap-doc-caption", "look-grey-muted", "snd-suspense-drone", ["anno-circle-callout", "dia-cause-map", "anno-source-label"], "红线把证据连起来"),
    ("ni-claim-evidence", "主张与证据", "documentary/claim-evidence", "rhy-tight-explainer", "newsroom", "cap-quote-serif", "look-neutral", "snd-news-bed", ["card-quote", "anno-source-label", "anno-box-label"], "每个主张旁边是它的证据"),
    ("ni-verification", "核实路径", "documentary/verification-path", "rhy-tight-explainer", "terminal-green", "cap-keyword-color", "look-cool-tech", "snd-minimal-ticks", ["scr-browser-frame", "scr-cursor-zoom", "anno-box-label"], "复现查证的每一步"),
    ("ni-riso-explainer", "套印解释", "documentary/mechanism-explainer", "rhy-hook-3s", "riso-duo", "cap-keyword-weight", "look-film-green", "snd-news-bed", ["comp-collage-layer", "sty-halftone", "data-map-route"], "网点印刷的拼贴解释"),
    ("ni-correction", "更正说明", "documentary/correction", "rhy-natural", "red-pen-review", "cap-phrase-clean", "look-neutral", "snd-voice-only", ["anno-strike-replace"], "旧结论被明确划掉"),
    ("ni-numbers", "数字说清", "documentary/numbers", "rhy-tight-explainer", "light-tech-board", "cap-keyword-color", "look-clean-bright", "snd-minimal-ticks", ["data-bar-chart", "data-number-impact", "anno-source-label"], "每个图表标口径"),
]
P["S29"] = [
    ("ev-chapters", "活动章节", "vlog-journey/event-chapters", "rhy-chaptered", "modernist-geometry", "cap-phrase-clean", "look-clean-bright", "snd-corporate-uplift", ["card-chapter", "card-lower-third"], "按议程章节组织"),
    ("ev-behind", "幕后", "vlog-journey/behind-the-event", "rhy-natural", "archive-typewriter", "cap-doc-caption", "look-doc-natural", "snd-ambience", ["data-timeline", "txt-typewriter"], "倒计时时间码"),
    ("ev-energy", "高能回顾", "vlog-journey/collective-moment", "rhy-beat-sync", "dark-liquid", "cap-3d-follow", "look-neon-cyber", "snd-beat-driven", ["av-beat-pulse", "tr-zoom-through"], "高潮镜头落在重拍"),
    ("ev-voices", "来宾声音", "vlog-journey/voices-of-event", "rhy-natural", "lifestyle-pictorial", "cap-speaker-color", "look-warm-life", "snd-ambience", ["card-lower-third", "card-quote"], "每位来宾一句原话"),
    ("ev-expo", "展会产品", "commerce/feature-to-action", "rhy-tight-explainer", "glassmorph", "cap-keyword-color", "look-product-true", "snd-corporate-uplift", ["anno-box-label", "card-lower-third"], "展台上的真实演示"),
    ("ev-performance", "演出完整", "vlog-journey/performance-breath", "rhy-observational", "film-leader-card", "cap-minimal-thin", "look-hk-night", "snd-ambience", [], "完整保留一首歌"),
]
P["S30"] = [
    ("fr-causal", "因果主线", "film-recap/causal-spine", "rhy-tight-explainer", "film-leader-card", "cap-cinema", "look-neutral", "snd-cinematic-swell", ["card-chapter"], "每段以“于是”连接"),
    ("fr-clue", "线索悬疑", "film-recap/clue-suspense", "rhy-hook-3s", "clipping-archive", "cap-keyword-color", "look-grey-muted", "snd-suspense-drone", ["anno-circle-callout", "cam-freeze-frame"], "线索定格圈出，答案延后"),
    ("fr-arc", "人物弧光", "film-recap/character-arc", "rhy-chaptered", "mono-portrait", "cap-quote-serif", "look-neutral", "snd-cinematic-swell", ["card-chapter", "card-quote"], "人物三次选择三张卡"),
    ("fr-irony", "戏剧反讽", "film-recap/dramatic-irony", "rhy-tight-explainer", "red-pen-review", "cap-keyword-weight", "look-neutral", "snd-suspense-drone", ["comp-split-screen", "anno-box-label"], "观众知道的写在角落"),
    ("fr-comic", "吐槽反应", "film-recap/comic-reaction", "rhy-fast-claim-first", "meme-red", "cap-variety", "look-neutral", "snd-variety-sfx", ["stk-reaction-burst", "cam-punch-in", "cam-freeze-frame"], "名场面定格配吐槽"),
    ("fr-close-reading", "场景细读", "film-recap/scene-close-reading", "rhy-observational", "quiet-whitespace", "cap-minimal-thin", "look-neutral", "snd-room-tone", ["anno-magnifier", "anno-box-label", "anno-spotlight"], "一场戏逐镜放大细节"),
    ("fr-micro", "一分钟讲完", "film-recap/micro-complete", "rhy-fast-claim-first", "black-yellow-heavy", "cap-word-slam", "look-neutral", "snd-beat-driven", ["card-title"], "一分钟一个完整因果"),
]
P["S31"] = [
    ("dp-hook-cut", "投流钩子切条", "multiplatform/hook-controlled", "rhy-hook-3s", "meme-red", "cap-pill-karaoke", "look-neutral", "snd-statement-hits", ["card-title", "card-cta-end"], "前三秒是全集最强冲突"),
    ("dp-previously", "前情提要", "multiplatform/layered-summary", "rhy-trailer", "film-leader-card", "cap-cinema", "look-neutral", "snd-suspense-drone", ["card-chapter", "tr-dip-color"], "黑场字卡“上集”"),
    ("dp-trailer", "预告片", "multiplatform/teaser-honesty", "rhy-trailer", "black-gold-premium", "cap-minimal-thin", "look-neutral", "snd-cinematic-swell", ["txt-gloss-sweep", "card-title", "tr-dip-color"], "声音先入，片名最后"),
    ("dp-character-card", "人物出场卡", "multiplatform/series-identity", "rhy-hook-3s", "black-yellow-heavy", "cap-keyword-weight", "look-neutral", "snd-statement-hits", ["cam-freeze-frame", "card-lower-third", "txt-slam"], "定格加人物身份牌"),
    ("dp-ancient-title", "古装题签", "multiplatform/series-identity", "rhy-trailer", "ink-xuan", "cap-vertical", "look-film-warm", "snd-cinematic-swell", ["txt-calligraphy-title", "tr-ink-bleed", "fx-snow-rain"], "书法剧名与墨晕"),
    ("dp-vertical", "竖屏重构", "multiplatform/subject-window", "rhy-natural", "quiet-whitespace", "cap-speaker-color", "look-neutral", "snd-room-tone", ["cam-reframe-follow"], "人物始终在竖屏中"),
    ("dp-commentary", "短剧解说", "film-recap/serial-bridge", "rhy-tight-explainer", "variety-color-caption", "cap-variety", "look-neutral", "snd-variety-sfx", ["card-chapter", "stk-reaction-burst"], "每集结尾留一个问题"),
]
P["S32"] = [
    ("va-variety", "综艺花字", "highlights/live-personality", "rhy-fast-claim-first", "variety-color-caption", "cap-variety", "look-high-key-summer", "snd-variety-sfx", ["stk-reaction-burst", "cam-punch-in", "stk-emoji-pop"], "反应花字只跟真实笑点"),
    ("va-deadpan", "冷面幽默", "pacing/comic-delay", "rhy-natural", "quiet-whitespace", "cap-minimal-thin", "look-neutral", "snd-silence-punct", ["cam-freeze-frame"], "笑点后留两秒空白"),
    ("va-meme-loop", "重复梗卡点", "highlights/callback-thread", "rhy-beat-sync", "meme-red", "cap-word-slam", "look-vhs-retro", "snd-beat-driven", ["cam-punch-in", "cam-shake", "av-beat-freeze"], "同一句话按节拍重复"),
    ("va-retro-tv", "老电视", "highlights/live-challenge", "rhy-chaptered", "pixel-retro", "cap-typewriter", "look-vhs-retro", "snd-retro-game", ["sty-vhs", "card-title"], "像素关卡字卡分章"),
    ("va-danmaku", "弹幕吐槽", "highlights/chat-response", "rhy-fast-claim-first", "anime-danmaku", "cap-danmaku", "look-airy", "snd-variety-sfx", ["card-social-post", "stk-emoji-pop"], "弹幕只用真实评论"),
    ("va-duo", "双人对口", "interview/comic-timing", "rhy-natural", "cute-sticker", "cap-speaker-color", "look-warm-life", "snd-variety-sfx", ["comp-split-screen"], "两人分色字幕"),
]
P["S33"] = [
    ("gm-esports", "电竞 HUD", "highlights/clutch-decision", "rhy-highlight-burst", "esports-hud", "cap-glitch-rgb", "look-neon-cyber", "snd-beat-driven", ["card-lower-third", "data-count-up", "cam-speed-ramp"], "残局决策慢放"),
    ("gm-combo", "连招可读", "highlights/combo-readability", "rhy-tight-explainer", "pixel-retro", "cap-keyword-weight", "look-neutral", "snd-retro-game", ["scr-keystroke", "anno-arrow-point", "cam-freeze-frame"], "按键序列同屏"),
    ("gm-comeback", "翻盘弧线", "highlights/comeback-arc", "rhy-montage-build", "holo-scifi", "cap-word-slam", "look-neon-cyber", "snd-cinematic-swell", ["data-line-graph", "tr-glitch"], "经济曲线反转"),
    ("gm-speedrun", "速通计时", "highlights/speedrun-attempt", "rhy-highlight-burst", "terminal-green", "cap-minimal-thin", "look-neutral", "snd-retro-game", ["data-count-up", "data-timeline"], "分段计时器常驻"),
    ("gm-world", "世界探索", "highlights/world-discovery", "rhy-observational", "soft-organic-gradient", "cap-minimal-thin", "look-golden-hour", "snd-ambience", ["card-title"], "第一次看见远景时不说话"),
    ("gm-failure", "失败教学", "highlights/learning-from-failure", "rhy-tight-explainer", "red-pen-review", "cap-keyword-color", "look-neutral", "snd-minimal-ticks", ["anno-red-pen", "cam-freeze-frame"], "失误点红笔复盘"),
]
P["S34"] = [
    ("sp-replay", "关键回放", "highlights/moment-replay", "rhy-highlight-burst", "deep-blue-impact", "cap-keyword-weight", "look-high-key-summer", "snd-cinematic-swell", ["cam-speed-ramp", "cam-freeze-frame", "card-lower-third"], "回放必标“回放”"),
    ("sp-technique", "技术拆解", "highlights/technique-breakdown", "rhy-tutorial-follow", "blueprint-line", "cap-keyword-color", "look-neutral", "snd-voice-only", ["anno-arrow-point", "trk-label-follow"], "跟踪标签标出跑位"),
    ("sp-turning-point", "转折点", "highlights/turning-point", "rhy-montage-build", "newsroom", "cap-phrase-clean", "look-neutral", "snd-suspense-drone", ["data-line-graph", "card-chapter"], "比分曲线上的转折"),
    ("sp-underdog", "弱者叙事", "highlights/underdog-context", "rhy-chaptered", "film-leader-card", "cap-cinema", "look-film-warm", "snd-cinematic-swell", ["card-lower-third", "data-timeline"], "赛前背景先于比赛"),
    ("sp-teamwork", "团队配合", "highlights/team-combination", "rhy-tight-explainer", "light-tech-board", "cap-phrase-clean", "look-clean-bright", "snd-minimal-ticks", ["anno-arrow-point", "dia-flowchart"], "传球路线画线"),
    ("sp-fan-energy", "现场声浪", "highlights/complete-possession", "rhy-beat-sync", "black-yellow-heavy", "cap-word-slam", "look-high-key-summer", "snd-beat-driven", ["av-beat-pulse", "cam-shake"], "进球时全场声音先于画面"),
]
P["S35"] = [
    ("mm-beat-hit", "强拍卡点", "music-montage/anticipation-hit", "rhy-beat-sync", "dark-liquid", "cap-lyric-karaoke", "look-neon-cyber", "snd-beat-driven", ["av-beat-freeze", "cam-whip-pan"], "切点落在强拍前一帧"),
    ("mm-graphic-rhyme", "图形押韵", "music-montage/graphic-rhyme", "rhy-beat-sync", "swiss-grid", "cap-minimal-thin", "look-neutral", "snd-beat-driven", ["tr-match-assist", "sty-duotone"], "形状相同处换镜"),
    ("mm-color-thread", "颜色线索", "music-montage/color-thread", "rhy-montage-build", "soft-organic-gradient", "cap-minimal-thin", "look-film-green", "snd-beat-driven", ["tr-dissolve", "bg-noise-texture"], "一种颜色贯穿全片"),
    ("mm-lyric-image", "歌词画面", "music-montage/lyric-image", "rhy-beat-sync", "ink-xuan", "cap-vertical", "look-film-warm", "snd-beat-driven", ["txt-calligraphy-title", "tr-ink-bleed"], "歌词关键词书法显出"),
    ("mm-memory", "回忆碎片", "music-montage/memory-fragments", "rhy-montage-build", "old-photo-album", "cap-minimal-thin", "look-archive-faded", "snd-beat-driven", ["sty-film-grain", "tr-light-leak"], "漏光转场连接碎片"),
    ("mm-dance", "舞蹈乐句", "music-montage/dance-phrase", "rhy-beat-sync", "acid-green-type", "cap-word-pop", "look-high-key-summer", "snd-beat-driven", ["cam-speed-ramp", "av-beat-pulse"], "动作在乐句末定格"),
    ("mm-quiet-build", "安静递进", "music-montage/quiet-build", "rhy-montage-build", "quiet-whitespace", "cap-cinema", "look-winter-blue", "snd-beat-driven", ["tr-dissolve", "cam-speed-ramp"], "前半无切点，后半加速"),
]
P["S36"] = [
    ("mp-claim-proof", "观点加证据短条", "multiplatform/claim-proof", "rhy-live-slice", "black-yellow-heavy", "cap-keyword-weight", "look-clean-bright", "snd-statement-hits", ["card-quote", "card-cta-end", "txt-per-word-rise"], "主张后三秒内给证据"),
    ("mp-silent-readable", "静音可读", "multiplatform/silent-readable", "rhy-tight-explainer", "swiss-grid", "cap-keyword-weight", "look-clean-bright", "snd-voice-only", ["card-title"], "关掉声音也看得懂"),
    ("mp-series", "系列标识", "multiplatform/series-identity", "rhy-hook-3s", "warm-orange-geo", "cap-gradient-fill", "look-warm-life", "snd-minimal-ticks", ["card-title", "card-cta-end", "card-logo-sting"], "每条同一个片头三秒"),
    ("mp-vertical-window", "竖屏主体窗", "multiplatform/subject-window", "rhy-natural", "quiet-whitespace", "cap-phrase-clean", "look-neutral", "snd-voice-only", ["cam-reframe-follow"], "主体始终在安全区内"),
    ("mp-teaser", "诚实预告", "multiplatform/teaser-honesty", "rhy-trailer", "film-leader-card", "cap-cinema", "look-neutral", "snd-suspense-drone", ["card-title", "tr-dip-color"], "预告里的每个画面正片都有"),
    ("mp-expert-recap", "专家速览", "multiplatform/expert-recap", "rhy-news-brisk", "light-tech-board", "cap-keyword-color", "look-clean-bright", "snd-news-bed", ["card-checklist", "card-chapter"], "一屏三点"),
]
P["S37"] = [
    ("lo-paired", "双语对照", "localization/bilingual-paired", "rhy-natural", "blue-professional", "cap-bilingual-stack", "look-neutral", "snd-voice-only", [], "两种语言同时完整"),
    ("lo-term-first", "术语优先", "localization/term-first-caption", "rhy-natural", "light-tech-board", "cap-bilingual-foreign-first", "look-neutral", "snd-voice-only", ["anno-box-label"], "术语首现给原文和解释"),
    ("lo-footnote", "文化注释", "localization/cultural-footnote", "rhy-natural", "lifestyle-pictorial", "cap-bilingual-stack", "look-neutral", "snd-voice-only", ["anno-source-label"], "文化梗用角注解释"),
    ("lo-revoice", "配音口型", "localization/lip-sync-performance", "rhy-natural", "quiet-whitespace", "cap-minimal-thin", "look-neutral", "snd-voice-only", [], "口型同步，不加字幕"),
    ("lo-screen-text", "画面文字本地化", "localization/screen-text-locale", "rhy-natural", "swiss-grid", "cap-phrase-clean", "look-neutral", "snd-voice-only", ["trk-mosaic", "txt-fade-rise"], "画面原文字被替换为目标语"),
    ("lo-sdh", "无障碍字幕", "localization/sdh-evidence", "rhy-natural", "newsroom", "cap-sdh-accessible", "look-neutral", "snd-voice-only", [], "声音描述写进字幕"),
]
P["S38"] = [
    ("cd-claim-chain", "主张链压缩", "pacing/claim-chain", "rhy-fast-claim-first", "swiss-grid", "cap-keyword-weight", "look-neutral", "snd-voice-only", ["card-chapter"], "每段只留主张和最强依据"),
    ("cd-breath", "保留气口", "pacing/breath-reset", "rhy-natural", "quiet-whitespace", "cap-phrase-clean", "look-neutral", "snd-room-tone", [], "缩短但不删呼吸"),
    ("cd-timed-chapter", "定时章节", "multiplatform/timed-chapter", "rhy-chaptered", "modernist-geometry", "cap-phrase-clean", "look-neutral", "snd-lofi-bed", ["card-chapter", "data-progress-ring"], "每章固定时长"),
    ("cd-backtrace", "结果倒叙", "pacing/result-backtrace", "rhy-hook-3s", "black-yellow-heavy", "cap-keyword-weight", "look-neutral", "snd-statement-hits", ["card-title", "tr-dip-color"], "先给结果再回到起点"),
    ("cd-music-density", "音乐密度", "pacing/music-density-release", "rhy-montage-build", "dark-liquid", "cap-minimal-thin", "look-neutral", "snd-beat-driven", ["av-beat-pulse"], "音乐决定哪里加速"),
    ("cd-silence", "静默对比", "pacing/silence-contrast", "rhy-unhurried", "mono-portrait", "cap-cinema", "look-bw-contrast", "snd-silence-punct", [], "最重要的一句前留白"),
]
P["S39"] = [
    ("rf-proof-ladder", "证据阶梯", "reference/proof-ladder", "rhy-tight-explainer", "light-tech-board", "cap-keyword-color", "look-neutral", "snd-minimal-ticks", ["card-step", "anno-source-label"], "证据逐级加码"),
    ("rf-sound-first", "声先于画", "reference/sound-before-image", "rhy-trailer", "film-leader-card", "cap-cinema", "look-neutral", "snd-suspense-drone", ["tr-dip-color"], "每段先黑场听声"),
    ("rf-palette", "克制色板", "reference/restrained-palette", "rhy-natural", "quiet-whitespace", "cap-minimal-thin", "look-grey-muted", "snd-room-tone", [], "只借参考片的色板"),
    ("rf-kinetic-limit", "有限动效", "reference/kinetic-with-limit", "rhy-fast-claim-first", "acid-green-type", "cap-word-pop", "look-neutral", "snd-statement-hits", ["txt-slam", "cam-punch-in"], "只借参考片的大字节奏"),
    ("rf-long-take", "长镜注意力", "reference/long-take-attention", "rhy-observational", "neo-chinese-minimal", "cap-vertical", "look-film-green", "snd-ambience", [], "借参考片的长镜头长度"),
    ("rf-shape-rhyme", "形状押韵", "reference/shape-rhyme", "rhy-beat-sync", "modernist-geometry", "cap-minimal-thin", "look-neutral", "snd-beat-driven", ["tr-match-assist"], "借参考片的形状匹配转场"),
]
P["S40"] = [
    ("ph-spatial-window", "空间窗口", "generation/spatial-window", "rhy-unhurried", "quiet-whitespace", "cap-minimal-thin", "look-neutral", "snd-ambience", ["cam-ken-burns"], "多张同地照片拼出空间"),
    ("ph-archive-letter", "照片来信", "generation/archive-letter", "rhy-unhurried", "old-photo-album", "cap-hand-note", "look-archive-faded", "snd-acoustic-vlog", ["cam-ken-burns", "txt-handwrite"], "旧照配手写信"),
    ("ph-time-pair", "两张照片的时间", "generation/time-pair", "rhy-natural", "swiss-grid", "cap-doc-caption", "look-neutral", "snd-room-tone", ["comp-split-screen", "tr-wipe"], "同角度两个年份擦除对比"),
    ("ph-annotated-proof", "图片举证", "generation/annotated-proof", "rhy-tight-explainer", "red-pen-review", "cap-keyword-color", "look-neutral", "snd-minimal-ticks", ["anno-circle-callout", "anno-magnifier"], "圈出图中的证据"),
    ("ph-parallax", "动态照片", "generation/still-attention", "rhy-unhurried", "lifestyle-pictorial", "cap-minimal-thin", "look-film-warm", "snd-ambience", ["cam-parallax-25d"], "照片里的空间动起来"),
    ("ph-gallery", "安静画廊", "generation/quiet-gallery", "rhy-observational", "neo-chinese-minimal", "cap-vertical", "look-morandi", "snd-room-tone", ["txt-fade-rise"], "一张一张不催促"),
]
P["S41"] = [
    ("ea-whiteboard", "白板动画", "generation/step-reveal", "rhy-tight-explainer", "whiteboard-marker", "cap-phrase-clean", "look-clean-bright", "snd-lofi-bed", ["dia-whiteboard", "anno-arrow-point", "txt-stroke-draw"], "手画出每个概念"),
    ("ea-paper-cutout", "剪纸寓言", "generation/illustrated-fable", "rhy-chaptered", "torn-collage", "cap-hand-note", "look-warm-life", "snd-acoustic-vlog", ["comp-collage-layer", "tr-paper-tear"], "剪纸人物讲寓言"),
    ("ea-data-story", "数据故事", "generation/number-to-scale", "rhy-tight-explainer", "light-tech-board", "cap-keyword-color", "look-clean-bright", "snd-minimal-ticks", ["data-bar-chart", "data-count-up", "data-map-route"], "数字换算成看得见的尺度"),
    ("ea-cause-map", "因果地图", "generation/cause-map", "rhy-chaptered", "blueprint-line", "cap-phrase-clean", "look-cool-tech", "snd-lofi-bed", ["dia-cause-map", "dia-flowchart"], "一张图越画越完整"),
    ("ea-math", "数学动画", "generation/analogy-with-return", "rhy-tutorial-follow", "quiet-whitespace", "cap-minimal-thin", "look-neutral", "snd-voice-only", ["dia-formula"], "类比后回到公式"),
    ("ea-3d-product", "3D 产品原理", "generation/product-form-study", "rhy-trailer", "holo-scifi", "cap-minimal-thin", "look-neon-cyber", "snd-cinematic-swell", ["dia-product-turntable", "anno-box-label"], "爆炸图拆解结构"),
    ("ea-kinetic-type", "动态字体", "generation/one-question-explainer", "rhy-fast-claim-first", "deep-blue-impact", "cap-word-slam", "look-neutral", "snd-statement-hits", ["txt-slam", "txt-scramble-decode"], "整片只有字"),
]
P["S42"] = [
    ("av-explainer", "讲解员", "generation/presenter-explainer", "rhy-tight-explainer", "light-tech-board", "cap-keyword-color", "look-clean-bright", "snd-voice-only", ["card-lower-third", "data-bar-chart", "comp-bg-replace"], "数字人只讲，证据用真实图表"),
    ("av-demo-handoff", "演示交接", "generation/presenter-demo-handoff", "rhy-tutorial-follow", "glassmorph", "cap-phrase-clean", "look-clean-bright", "snd-lofi-bed", ["comp-pip", "scr-cursor-zoom", "comp-chroma-key"], "讲到操作就交给真实录屏"),
    ("av-accessible", "无障碍讲解", "generation/accessible-presenter", "rhy-natural", "health-fresh", "cap-sdh-accessible", "look-neutral", "snd-voice-only", [], "大字幕加慢语速"),
    ("av-two-voice", "双人对话", "generation/two-voice-dialogue", "rhy-natural", "warm-orange-geo", "cap-speaker-color", "look-warm-life", "snd-lofi-bed", ["comp-split-screen"], "两个角色分色对话"),
    ("av-character", "角色旁白", "generation/character-narrator", "rhy-chaptered", "cute-sticker", "cap-word-pop", "look-pastel-book", "snd-acoustic-vlog", ["stk-sticker-bounce"], "卡通角色串场"),
    ("av-local-repair", "局部修补", "generation/presenter-local-repair", "rhy-natural", "blue-professional", "cap-phrase-clean", "look-neutral", "snd-voice-only", [], "只重生成说错的那一句"),
]

# Packs whose route needs an external service in addition to their components.
SERVICE_REQUIREMENTS = {
    "lo-revoice": ["gen"],
}
