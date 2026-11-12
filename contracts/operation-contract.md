# 原子操作合同 v1（本地 runtime 实现）

本文件的精确 JSON 字段、绝对路径及 SHA-256 约束适用于选择本库 `editing_runtime.py` 时的本地调用。通用 Skill 的能力和跨工具结果交接见[能力交接合同](capability-handoff.md)：运行 Agent 可选实际可用的编辑器 API、插件、CLI 或本地执行器，不要求所有环境先安装本库 MCP、SQLite 或特定模型。

实际实现入口：`runtime/editing_runtime.py`，完整入口见 [registry](../registry/skills.json)。下表记录基础与常用操作，其他能力以各专项合同和实际派发代码为准；不得用近似操作替代后报告成功。

## 调用

```bash
python3 runtime/editing_runtime.py doctor --ffmpeg /absolute/ffmpeg --ffprobe /absolute/ffprobe
python3 runtime/editing_runtime.py run --request /absolute/request.json --work-dir /absolute/new-run --ffmpeg /absolute/ffmpeg --ffprobe /absolute/ffprobe
```

相对位置以库根目录为基准。也可使用 `EDITING_FFMPEG` / `EDITING_FFPROBE`；不内置用户机器路径。每次 work-dir 必须不存在，以防覆盖先前产物；失败产物保留，修复后用新运行目录引用最新有效状态。

`source = {path: 绝对路径, sha256: 原始字节 SHA-256}`。只有首次 `media-inspect` 可省略 sha256。所有其他操作必须提供非空、64 位小写哈希。来源变化立即报错，不根据文件修改时间猜测未变。

所有区间为源素材秒数、半开 `[start,end)`，数值必须有限。转写词时间若是估算，不能自动成为安全剪点。渲染不自动挪切点或保护残句；选段责任在调用方复杂 Skill。

## 已实现操作

指定文字与当前作品输出时间窗：见[caption-coverage-check](../atomic/caption-coverage-check/SKILL.md)。请求含document、expected_document_sha256及非空requirements；字面匹配与连续窗口覆盖不认证真假、最终渲染可见性或声音一致。

| operation | 请求字段（除 operation） | 结果 |
|---|---|---|
| media-inspect | source | 媒体规格、时长、流信息、源哈希 |
| frame-extract | source, times: 秒数数组 | 指定时间处解码帧 PNG；不是内容挑帧 |
| audio-extract | source, start, end, sample_rate, channels | PCM WAV；无音频明确返回 NO_AUDIO |
| timeline-render | plan, audio_backend、source_consumption（可选） | normalized-plan.json、source-binding.json、preview.mp4；仅按给定顺序拼接 |
| caption-map | plan, cues, boundary_policy | 原文不变的输出时间字幕 JSON/SRT |
| timeline-patch | plan, expected_revision, allowed_clip_ids, changes | 新计划版本、修改/未改片段、失效项 |
| media-qc | source, expected | 技术检查 JSON；不代替内容、观看与听检 |
| audio-mix | source, base_gain_db, tracks | 按明确音频范围/位置/增益混合，输出 mixed.mp4；不裁短超长语音 |
| caption-burn | source, font, font_family, font_size, margin_v, color_rgb, cues | 明确字体和样式烧录 ASS，输出 captioned.mp4 |
| tts-macos | text, voice, rate | 显式 macOS say 提供方生成本地 WAV，回报真实时长，不提供逐词对齐 |
| transcript-import | transcript | 校验源绑定逐词转写，见 [口播合同](speech-contract.md) |
| speech-transcribe-local | source, audio_stream, start, end, model_lock, environment_lock, language, beam_size, vad_filter, condition_on_previous_text, cpu_threads | 固定本地模型输出语音观察，见 [本地ASR合同](local-asr-contract.md)；不自动清理文字或决定删剪 |
| speech-plan-compile | transcript, expected_revision, output, segments, protected_word_ids, allow_reorder | 明确词选择编译剪辑计划，见口播合同 |
| screen-focus | source, crop, output, highlights | 固定裁切、等比缩放、定时框选，见 [教程合同](tutorial-contract.md) |
| tutorial-plan-compile | plan, expected_revision, steps, result_cues | 教程证据窗口、因果依赖及结果提示映射，见教程合同 |
| work-version | action, store 及动作字段 | 同一作品初始化/读取/提交/追加式恢复，见 [作品合同](work-contract.md) |
| host-bridge | action 及宿主快照/Work 状态字段 | 宿主中立映射、受限补丁与手改导入提案，见 [宿主桥合同](host-bridge-contract.md)；不代表编辑器保存 |
| work-delivery | action, store 及交付事件字段 | 严格媒体当前交付选择/读取/恢复/清除，见 [work-version](../atomic/work-version/SKILL.md) |
| generation-task | action, store 及任务字段 | 生成任务生命周期、输出身份、账单与采用闸门，见 [生成合同](generation-task-contract.md) |
| model-text | action、store 及文本调用字段 | 宿主配置的 HTTPS 文本/function Provider、冻结请求、单次发送与费用账本，见 [生成合同](generation-task-contract.md) |
| model-text-deepseek | action, store 及文本调用字段 | DeepSeek 文本/function 单次请求与账单登记，见 [生成合同](generation-task-contract.md)；不生成图片/视频 |
| timeline-revise | base_version, document, expected_document_sha256, candidate, scope | 明确候选的范围校验、差异与失效项，不自动应用 |
| work-render | store, expected_version、source_consumption（可选） | 同一版本的片段/音轨/字幕渲染与输出绑定 |
| sync-offset-measure | method, reference, follower, max_spread_seconds, min_span_seconds 及方法字段 | 多窗口/标记偏移测量，不自动应用，见 [多机位合同](multicam-contract.md) |
| multicam-plan-compile | master, expected_revision, output, segments, allow_reorder, allow_session_reuse | 明确机位/节目声映射为 WorkDocument，见多机位合同 |
| evidence-plan-compile | document, expected_document_sha256, units, occurrences, required_units, chapters | 声画证据、显式依赖与实际章节时间映射，见 [证据合同](evidence-contract.md)；不判断重要性或决议真伪 |

不接受未知字段，以免用户写了转场或自动高光后被悄悄忽略。片段可显式指定恒定 `speed`，省略为 1，范围为 0.5–2；不支持速度曲线或区间内变速。当前渲染支持 contain 黑边适配与 cover 中心裁切，调用方必须明确选择；不声称主体智能跟随。支持不同素材帧率转为明确的输出帧率，每段按最近输出帧数取整，量化误差写入 normalized-plan。不足一输出帧的区间拒绝；无音频的片段显式合成静音。

参考稿与识别稿的确定性文字差异见[文字对照合同](text-comparison-contract.md)，operation为`transcript-reference-compare`。不生成更正稿或剪辑切点。

## ExecutionPlan

```json
{
  "schema": "execution-plan/1",
  "fps": "30",
  "width": 1920,
  "height": 1080,
  "fit": "contain",
  "sources": {"s01": {"path": "/absolute/authorized-source.mp4", "sha256": "填写真实64位哈希"}},
  "clips": [
    {"id": "c01", "source_id": "s01", "start": 12.0, "end": 18.5, "gain_db": 0}
  ],
  "allow_source_reuse": false
}
```

timeline-render 产生新的剪辑时间轴，不自动继承输入容器中未经重映射的章节，避免源章节延长成片或保留错误位置。evidence-plan-compile 的显式 chapters 仍是受保护的 JSON 时间映射与导航报告，不因本策略被删除，也不等同已写入 MP4 章节轨；当前 ExecutionPlan 没有容器章节导出字段。此输出策略只作用于 timeline-render，不对独立混音、字幕烧录或视觉叠层操作全局清除元数据。

此示例不是可直接执行的素材引用。片段 ID 唯一，sources 列出已登记的真实素材；画幅为正偶数，帧率支持 `30000/1001`。同源重叠默认拒绝：按已验证的素材字节 SHA-256 识别来源，不同 source_id、软链接或同字节副本不能绕过此限制；同源不重叠片段仍允许。有意回看需显式 `allow_source_reuse: true`。不静默裁掉越界部分、跳过无效段或补造镜头。

片段可选 `mute: true/false`，默认 false；必须布尔类型。true 时内嵌声音显式置零，gain_db 保留但不作用；不以 -120dB 近似静音。片段可选 `speed`（有理数字符串或数值，0.5–2，默认 1）；归一化计划返回恒定速度、量化后的有效源终点和 source_to_output_map。按输出帧数取整，短于一帧拒绝；末尾量化补帧不扩张有效源区间。省略 audio_backend 时，仅实际有效源窗内有可消费的非1倍速原声才选择默认 R3 流式后端；1x/静音/量化后已无原声使用身份或静音路径，无 helper 门槛。显式旧 atempo 或 v4 见下节；真实听感仍须另验。无音频段继续补静音。

## 字幕与局部修改

字幕 cue 包含 `id/source_id/start/end/text`，可选 `style_override` 仅允许与 caption-burn 相同的字号/颜色/边距字段并按目标画布校验；跨片段映射保留该对象，JSON 载有样式，SRT 不承载样式。`reject-partial` 阻止原句被切成半句字幕；`clip` 仅在调用方明确要求时裁切显示时间，并标记 partial，不自行改写句子。重复使用素材时字幕映射到每次实际使用的位置。caption-map 不烧录或识别；烧录由 caption-burn 完成，本地识别观察由 speech-transcribe-local 提供，其他云服务和独立强制对齐仍未接入。

局部修改 `changes = [{clip_id, set:{start/end/gain_db/speed}}]`，只允许显式字段更新，不删除/重排/增添片段。`expected_revision` 是当前计划规范 JSON 的 SHA-256，通过 runtime.fingerprint 计算。冲突拒绝；未列入 allowed_clip_ids 的片段冻结。改变片段时长会使后续输出位置变化，即使源区间不变；若用户要求后段时间也不动，复杂层必须采用等时长替换或说明冲突，不能谎称仅改了局部内容。

## 回执与 QC

audio-mix 的每轨为 `{source,start,end,output_start,gain_db}`；原片音量由 base_gain_db 给定，可选 base_gain_windows 为有序不重叠的 `{start,end,gain_db}` 数组，按窗口设置绝对增益，精度为音频帧边界。超过画面范围拒绝，不自动拉伸或截断语音。混音不做主观对白避让，也不自动限幅或平滑增益；实际音量/峰值仍需检查。

caption-burn 的 cues 使用输出时间，字段为 start/end/text，可选非空 style_override 仅允许 font_size、color_rgb、margin_v，未覆盖字段继承全局。字号与边距仍按实际画布校验，局部字体及任意 ASS 指令不支持；font 是带哈希的本地字体。color_rgb 使用六位十六进制 RGB，font_size/margin_v 按视频画布像素；当前底部居中、黑色 1px 描边。不支持的 ASS 控制字符拒绝而不改写。字体 fallback 与字形完整性必须检查实际输出。

每个运行写 request.json 与 receipt.json，绑定代码版本/哈希、工具二进制哈希、请求指纹、实际产物哈希、成功或错误。SUCCEEDED 只说明该原子操作完成；技术 QC 即使全部通过也返回交付 DEGRADED，因为内容/画面/听检尚未完成。

技术 QC 的 expected 显式给出 duration、duration_tolerance、width、height、audio_required，并真实完整解码。当前不检测黑帧、静音、峰值、口型或内容错误，不能声称这些检查已通过。

高光相关操作 `media-signal-scan` 与 `event-plan-compile` 见 [高光观察与事件合同](highlight-contract.md)。

明确音频首尾淡变见[audio-envelope](../atomic/audio-envelope/SKILL.md)，输出派生音频后按实际回执绑定作品。

## 默认与显式本地音频后端（开发态）

timeline-render、work-render 当前作品/preview_candidate，以及批处理job，可选 audio_backend。省略时对实际有效源窗内可消费且非1x的原声使用本地 pinned `rubberband-r3-stream-v5`；其他片段继续身份或已声明静音。不会为了不消费的原声加载 helper，不把已量化截掉的尾部算作 DSP 输入。默认 helper 为当前 runtime 目录的 `rubberband-offline-f32-stream-v5`；缺失/字节漂移明确失败，不悄悄回退 atempo。Agent 也可以显式选择自身编辑工具，此为本库可选本地执行器的策略，不是通用 Skill 全局依赖。

```json
{"audio_backend":{"kind":"rubberband-r3-stream-v5","helper":{"path":"/absolute/helper","sha256":"实际64位SHA"},"stage_timeout_seconds":600}}
```

兼容显式 kind=ffmpeg-atempo（不接helper）和历史rubberband-r3-v4（要求原pinned helper，保留256MiB整段输入上限）。新stream-v5只接受当前封存 binary SHA，48kHz mono/stereo f32、0.5–2恒速。source raw通过同一regular只读FD执行两遍study/process，4096帧块不变；实际消费字节的SHA/帧数/长度分别核对、相互相等并等于调用前源PCM，完成前再核源/输出/helper身份。固定缓冲替代两份整段数组，数值溢出/有限性/短读/rewind/写入/close均拒绝；磁盘预检不替代实际IO错误处理，也没有整个进程RSS硬上限。

source_time_precision=SAMPLE_RESOLVING继续按原样本观察；stream-v5对COARSE_UNPROVEN沿用普通播放的单连续消费交集及屏障规则，包括observed-only或完整组解释。已核空头尾可以补明确静音，内部缺口/相位冲突拒绝，不能用policy字符串冒充已验证Vorbis组。粗钟仍未证严格样本连续性；普通渲染没有SOURCE COMPLETE信用，严格公开证据/逐样本冻结规则不松。

视频帧取整和effective_source_end保持；有效源终点可短于请求终点，不能称必要尾音完整。精确有理speed与binary64 time_ratio分别记录；helper自然输出按库std::round目标，48kHz视频槽按原ties-even另算，尾补零或有限舍入裁剪明确报告，不拿补槽伪造自然输出。源float不先夹s16；实际立体声矩阵和gain后同次扫描样本数/峰值/字节SHA，再核编码输入；风险峰值拒绝，不重复gain。PCM技术检查不认证AAC峰值、接缝、听感或语义。

stage_timeout_seconds为1–7200的显式每阶段上限，原值保留；没有提供时，以输出时长自动取max(300,min(7200,ceil(2×duration)))。源PCM物化、DSP、目标矩阵、最终编码及全帧计数使用同预算并留证；独立流/时窗metadata探测仍按原有限探测预算。不是整任务总时限或资金预算，显式小预算不能被自动放大。可捕获取消/超时终止本次拥有的子进程组并保存诊断，Work子取消传播到父；强制杀宿主/断电不承诺终态。

历史证据快照（当时范围）：真实压力证据仅为已有32×32合成静音双声道1670秒主片段在0.5x下完整输出3340秒/100200帧，helper峰值RSS约9.1MB只适用于此例；另有非零短例和混合70帧。当时尚无六组合、任意复杂声音、长片听检、跨平台安装、宿主或发行验证。Work/batch记录请求及实际子回执/helper身份；当前作品文档和历史不写入后端参数。RUNNING恢复的本轮测试是隔离SQLite受控回拨＋实际完整回执读回，不能冒称真实崩溃恢复。 后续[六格技术接收](../docs/evidence-scope.md)与[30fps长Work接收](../docs/evidence-scope.md)已限范围补证；现行范围以[CURRENT_STATUS](../docs/evidence-scope.md)顶部为准，完整声音／听检／安装／宿主／发行仍须另验。

## 原媒体消费绑定 v1

`timeline-render`、`work-render`（包括候选预览）及 `work-batch-render.prepare.jobs[]` 可提供同一个可选字段：

```json
{"source_consumption":{"schema":"source-consumption/1","mode":"snapshot","prepare_timeout_seconds":300,"reserve_bytes":67108864}}
```

`schema` 和 `mode` 必填；仅支持 `boundary`、`snapshot`，不支持的显式值拒绝。省略整个字段等价于 `boundary`。准备／每次完整复核的超时为 1–7200 秒整数，默认 300；`reserve_bytes` 为至少 1 MiB 的整数，默认 64 MiB，是调用方为输出等留下的磁盘余量，不是成片大小保证或整任务磁盘硬上限。快照前对按来源路径去重的总字节加余量预检空间。逐块读取内存有界，可捕获取消；准备失败不启动渲染，失败诊断保留。

两种模式都在素材探测／时钟观察／媒体消费前后完整复核原媒体；来源内容或路径绑定变化必须失败，失败文件保留为诊断，不能自动采用。`boundary` 的前后哈希不能识别期间 A→B→A 并恢复的全部变化。`snapshot` 在本次新工作目录生成普通独立副本，复制与目标重读均核完整 SHA，采用独占创建和只读文件／目录；探测、时钟与实际渲染共同消费副本。副本不用源文件硬链接，原计划的逻辑路径、SHA、剪辑参数与作品版本不变。副本被改或原媒体在消费中变化仍失败。任务拥有的目录与只读权限不能抵抗同权限恶意进程，本模式不宣称宿主安全隔离或任意竞态免疫，不授予来源声学精度或内容通过。

`source-binding.json` 使用 `source-consumption-receipt/1`，记录选择、原逻辑路径／SHA、执行路径、边界观察与 `VERIFIED`／`FAILED`；`adoptable` 只表示该来源检查通过，是采用的必要条件，不是作品采用授权。成功结果引用其路径和 SHA；失败操作不发布成功结果。重复 clip 共享同一来源副本。Work 将主轨、显式附加音轨、视觉层和字幕字体纳入同一消费范围，在开始渲染验证前准备；当前作品和候选预览沿用相同规则。

Work 最终 `render-binding.json` 保留原选择请求与请求摘要、实际消费选择和子回执摘要。批次清单透传原字段，恢复时核实际选择、来源绑定、子回执与源文件当前身份；来源漂移或快照缺失使历史产物不能被当作有效缓存。此策略不改 WorkDocument，也不绕过技术／内容 QC 或当前版本采用要求。

## 普通播放的 Vorbis 块时钟

Matroska/WebM Vorbis 的粗1ms时基，仅在真实 SimpleBlock 的有界头部解析、完整包帧一一匹配、样本数与包长度一致、全局共同相位约束成立时，给普通播放提供组时钟假设。支持实际 EBML、Xiph 和无 lacing 单帧，其他结构保留原观察。Xiph/无 lacing 字节规则依据 RFC9559 10.3.1–10.3.2：https://www.rfc-editor.org/rfc/rfc9559.html#section-10.3 。多候选头只排除超文件/大小上限的不可能声明；仍有多个可行头则拒绝。跨窗口同块去重和冲突屏障保持。

这一假设不证明物理样本无间断。strict 证据仍使用 observed_intervals，source_time_precision 保持 COARSE_UNPROVEN；不能授予样本精度、语义、听检或人评信用。
