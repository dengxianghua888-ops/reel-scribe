# 同一作品与局部修改合同 v1

执行入口：[editing_runtime.py](../runtime/editing_runtime.py)，实现：[work_ops.py](../runtime/work_ops.py)。SQLite 存当前版本和完整历史，调用目录存不可变请求/回执。store 放在作品独立目录，不放在会被当作不可变产物归档的操作目录里。

## WorkDocument

```text
schema: work-document/1
plan: ExecutionPlan
captions: {caption_id:{clip_id,start,end,text}}
caption_style: null 或 {font:{path,sha256},font_family,font_size,margin_v,color_rgb}
audio_tracks: {audio_id:{source:{path,sha256},start,end,anchor_clip_id,offset,gain_db}}
style_bindings: {"*"或clip_id:{family,style_id,version,card:{path,sha256},parameters:{...}}}
notes: {稳定备注ID: JSON值}
visual_layers: 可选ID字典，见叠层合同
evidence_protection: 可选 work-evidence-protection/1，见下方内容保护
```

captions 的 start/end 是相对锚定 clip 成片开始位置的秒数，一句字幕可跨画面切点，但不得超过全片或与别条重叠；文本不自动改写。audio_tracks 的 start/end 是音频源秒数，offset 相对 anchor_clip_id 的成片开始位置；anchor 为 null 时 offset 为全片绝对时间。负 offset 允许，但最终输出起点不得小于零。

删除锚定片段时必须显式迁移/删除其字幕、音轨和局部风格；时序重排时锚定内容随片段移动。语义是否仍成立要由复杂层复核。改变片段 speed 会重算输出位置及源到成片时间映射，锚定字幕、音轨、叠层即使字段未变也要按覆盖变化显式纳入对应 caption_ids/audio_ids/visual_ids 范围并复核。静态全片配乐可使用 null 锚点，不能默认随某个镜头移动。

style_bindings 是创作记录，不是自动生效的滤镜/节奏宏。真正变化要落在明确操作字段；代码不会把抽象 parameters 自行变成剪辑决定。文档当前不包含原生编辑器选区/播放头、复杂多轨动效，不宣称已经同步整个宿主。

叠层的 anchor_clip_id/offset_frames、范围复核与覆盖限制见[叠层合同](visual-layer-contract.md)。

## work-version

各请求共有 `operation: work-version`、`store: 绝对SQLite路径`、`action`。

| action | 其余字段 | 行为 |
|---|---|---|
| init | work_id, document, message, author | 新建存储，现有文件拒绝覆盖，首版sequence=1 |
| read | 无 | 返回当前document/version/sequence/document_sha256和历史摘要；外部媒体不在此步重验 |
| commit | expected_version, candidate:{path,sha256}, message, author | 数据库写锁内重验候选和范围，并比较当前版本后追加 |
| set-protection | expected_version, protection, change_basis, message, author | 仅登记/修订内容保护，或以 protection:null 显式撤销；基于当前版本追加，其他文档字段不变 |
| restore | expected_version, target_sequence, message, author；可选 style_resource_relocations | 验证历史源依赖，将历史内容追加为新版本；可选参数仅重定位同 SHA 样式卡，仍完整校验；不删除中间版本 |
| relink-style-resources | expected_version, relocations, message, author | 同作追加仅样式卡 path 的维护版本；保留旧历史，媒体/保护本次未校验 |

author 为 agent 或 human，表示提交来源声明，不能把测试注入写成真实用户操作。版本令牌绑定 work_id、递增sequence与文档哈希；内容恢复相同也不会使旧候选重新有效。锁冲突返回 WORK_BUSY，无盲目自动覆盖或重试。

`commit` 从同一次 UTF-8 候选字节读取核对请求 SHA 并解析文档；范围检查完成后、追加 revision 前再次检查该文件摘要。候选发生可观察变化则拒绝且不移动 Work 头，也不追加采用记录，不能在记录候选 A 的 SHA 时消费候选 B。该读回不替代当前版本 CAS、范围校验或真实媒体评审，也不是持续文件锁。

`relocations` 为非空数组，每项严格为 `{style_key,from:{path,sha256},to:{path,sha256}}`。key 必须已存在且不重复，from 必须逐字段匹配当前文档 card，to 只能是不同的规范绝对路径和同一 SHA 的已备妥普通文件；不允许 symlink、改卡语义/version/parameters 或其它字段。旧 from 文件可已丢失/被替换，不据此更新原 expected SHA。锁内 CAS、目标字节两次核查和路径之外文档完全一致检查通过后，沿同 work_id 追加 seq+1；不改旧行、不 init 新作品。回执 `resource_binding_validation=HASH_MATCHED`、`media_validation=NOT_RUN`、`semantic_review=NOT_RUN`、`protection_validation.validated_this_operation=false`；保护字段字节保持不等于覆盖重验通过。新令牌使旧候选、宿主/媒体绑定和交付选择失效，不删除旧输出或事件。

`restore.style_resource_relocations` 使用同一数组，from 绑定 **目标历史文档** 的 card。只变换目标副本 path，随后照旧完整 validate_document（媒体、字幕、叠层、音轨和保护）；任何失败均不追加版本。没传参数时不自动搜索或替换历史引用。历史内容与旧令牌不因迁移重新生效；不要把受控 validator 的测试成功称为真实恢复通过。

SQLite 提交是应用成功的权威边界。若提交后 work-state.json/receipt 导出失败，读取当前库查明状态；不要删除数据库或重复 init。空/不完整初始化文件要保留并诊断，不把文件存在等同成功。

## timeline-revise

字段：operation、base_version、document、expected_document_sha256、candidate、scope。其中 document 来自最近 read；candidate 是复杂层已决定的完整新 WorkDocument。

```text
scope: {
  clip_ids: [], source_ids: [], caption_ids: [], audio_ids: [],
  style_keys: [], note_keys: [], output_fields: [], caption_style: false,
  freeze_positions: [], freeze_duration: false, visual_ids: []（可选，默认空）
  evidence_mapping: false（可选布尔值）
}
```

- clip_ids 列出允许改/增/删/移的稳定ID，其他片段数据与相对顺序保持。参数明确的切点修改也可继续用已有 timeline-patch，但进入作品前须用本合同登记。
- source_ids 允许改来源；被改来源影响到的全部片段也必须在范围内，不能暗改冻结片段。
- output_fields 仅限 fps/width/height/fit/allow_source_reuse；画幅/帧率/fit 是全局影响，存在冻结片段时拒绝。
- 字幕、音轨、风格、备注按独立 ID 控制，改变镜头源内容或速度时相关字幕/音轨/叠层必须纳入复核范围。范围声明本身不证明复核质量。
- freeze_positions 列出输出起止帧和帧率都要保持的旧片段；freeze_duration 锁全片总帧数与帧率。
- evidence_mapping 对已有内容保护的速度变化也必须显式为 true；它只开放既有内容保护的 occurrences/chapters 映射变化；不能增删保护、重写 units/required_units，映射更新仍须通过完整来源覆盖和依赖校验。

输出 candidate.json（包含基础版本、基础文档哈希、新文档与范围）和 revision-diff.json。差异包含源内容变化、片段顺序、输出位置变化、字幕/音轨映射变化和失效项。生成不等于提交，提交端必须重新计算检查，不能信任外部报告说“通过”。

## 随作品版本保存的内容保护

可选 `evidence_protection` 字段包含 `schema: work-evidence-protection/1`、`units`、`required_units`、`occurrences`、`chapters`，后四项采用[声画证据合同](evidence-contract.md)。保护进入完整文档哈希与 SQLite 历史，每次文档校验复用相同覆盖算法。旧作品可以不含此字段；文档中显式 null 无效，空保护不能绕过合同。

普通 timeline-revise、commit 和 work-variant-create 不得增删保护或改动其 schema/units/required_units。重排或更换承载对象时，复杂层显式提交 `scope.evidence_mapping:true` 并更新 occurrences/chapters；覆盖、模态和依赖必须继续成立。已有明确 speed 的 0.5–2 倍恒速可在授权 clip 与 evidence_mapping 范围内保留普通内容保护：仍使用原来源、完整单元及依赖，按有理时间映射重新验证；截断、重复、重排、静音、错源以及位置/总时长冻结冲突仍拒绝。此普通范围保护不认证实际声音、逐样本/像素冻结或严格 SOURCE COMPLETE；公开严格证据编译仍拒绝变速承载。不能以撤保护、换源或伪造派生产物获得通过。commit 以 SQLite 当前文档为比较权威，不信任候选自报的基础；预览无数据库权威，伪造预览基础不构成成功采纳。

登记或修改保护使用独立 `set-protection`，必须给出非空 `change_basis`、准确 `expected_version`、message 和 author。记录前后保护指纹及依据，不同时改内容。`protection:null` 是显式撤销，不能为了让普通缩短通过而自行调用；复杂层须依据本次真实用户意图决定，冲突时保留保护并说明。author 和 change_basis 是调用方声明，不是身份认证或批准凭证。

完整 restore 恢复目标历史文档中的保护存在性和映射，追加新令牌；这可能恢复到登记保护之前的版本，因此必须符合用户要求的完整恢复范围。派生版本继承保护；候选不能绕过继承。任何文档变化都会使绑定旧文档哈希的 evidence-map 失效，当前校验通过不自动生成新的外部报告。保护只保证已声明单元的覆盖，不认证原话解释、声学词界、可听性或未声明的必要语境。

## work-render

字段：operation、store、expected_version。依赖 [timeline-render](../atomic/timeline-render/SKILL.md)、[audio-mix](../atomic/audio-mix/SKILL.md)、[caption-burn](../atomic/caption-burn/SKILL.md)、[media-qc](../atomic/media-qc/SKILL.md)。

从一个版本快照渲染，依次保留timeline/audio/visual/captions/qc子操作回执（无叠层时略过visual）。最终视频路径与哈希写在 render-binding.json；不固定猜 final.mp4。版本在渲染期间变化时保留旧版产物，但 current_at_finish=false，不能宣称当前作品已导出。

## 局部恢复与完整恢复

“整部作品回到版本1”用 restore 追加历史内容；“只恢复字幕，保留刚改的音量”从历史快照复制字幕到当前候选，只开放相关 caption_ids，走 timeline-revise→commit。后者不能直接整版restore，否则会覆盖后续其他编辑。

当前是本地单作品服务和可重渲染JSON，不是原生编辑器双向同步。没有导入适配器时需要先将受支持状态明确转换；不支持的特效/轨道保留原工程并报告阻塞，不能丢弃后宣称完整接管。

## work-delivery（当前本地技术候选扩展）

`operation: work-delivery` 使用与 work-version 相同的本地 SQLite 作品库。首次写选择事件时，在现有 schema v1 上增建 `delivery_events`；不修改文档版本或头。请求均含 `store` 绝对路径与 `action`：

- `read`：返回当前作品头和 `STRICT_MEDIA_TECHNICAL_CANDIDATE`，或带明确原因的 `RENDER_FALLBACK`。回退表示调用方按既有 work-render 路径处理，不表示自动启动渲染。读取前重验回执、绑定、请求、脚本和媒体字节。
- `select`：需 `expected_version`、`expected_event_id`（首次为 null）、严格 helper 的 `receipt`/`binding` 路径及 SHA，以及 `decision`。仅 SUCCEEDED 回执、完整证据文件、当前作品头和媒体哈希一致才能追加事件。
- `restore`：需当前 `expected_version`、`expected_event_id`、历史 `target_event_id` 与 `decision`；仅可选回仍匹配当前作品头且媒体有效的历史事件，追加新事件。
- `clear`：需当前 `expected_version`、`expected_event_id` 与 `decision`；追加事件并回到普通 work-render 路径。

`decision` 为 `{actor: agent|human, reason: 非空字符串, review_refs: [{path,sha256},...]}`。它记录声明和证据引用，不认证真人身份，也不把技术候选自动变成可发布交付。所有写动作使用作品库 `BEGIN IMMEDIATE` 与作品头、事件双重 CAS；写入事件后保留作品 revisions 和原媒体。work-version 的内容 restore 会更换版本令牌，旧选择在 read 时因版本不符回退。

当前候选返回 `publishable:false`，它只是本地技术回执中的未认证标记，必须原样保留。复杂层按[本次交付报告](editorial-contract.md#本次交付报告)汇总同一产物的技术、内容、完整画面/听检、输出读回与未决问题，判定本次交付范围；普通成片或 SRT 交付不以制造真人修改事件为前置，库级 D6/G5 及本次实际要求的同作修改/恢复分别验收。该结论不回写技术回执，也不改变本操作的事件、CAS、选择或回退规则。仅在明确承诺某一目标编辑器原生工程时，才追加该编辑器的打开、修改、导出和重开兼容证据。若回执或媒体缺失、哈希漂移，read 返回带原因的回退；消费者不得把存在的旧 MOV 自行当作当前交付。

## 可选渲染策略

work-render 的当前作品和 preview_candidate 可传入 operation-contract 定义的 audio_backend；只传播到本次子时间线和 render-binding，不更改 WorkDocument/版本。省略时按实际有效源窗选择默认流式R3或无需DSP的身份/静音路径；旧atempo可显式选，真实听感和R01完整声学验收仍未闭合。helper 只在实际 DSP 时需要，preview/current 共用 render_document；当前组合仅以隔离短预览和完整原源文档恢复验证，不代表真实项目成片、人评或宿主验收。

同样接受 [原媒体消费绑定 v1](operation-contract.md#原媒体消费绑定-v1) 的 `source_consumption`。省略时完整前后复核；显式快照必须在渲染验证前准备，主轨与附加音轨／视觉层／字幕字体使用同一份任务内副本。字段通过 Work 与批次逐层保留，最终绑定关联实际模式、来源记录与子回执 SHA。来源或副本发生可观察变化时父操作失败，不发布 `render-binding.json`，失败子预览不能成为有效作品产物。保护范围限于合同中声明的本地条件，不授予内容、听检或逐样本冻结验收。
