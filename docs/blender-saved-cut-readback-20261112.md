# Blender 保存硬切工程的受限读回

新增 `tools/editor-adapters/blender_cut_readback.py`，限定 Blender 4.3.2 和现有产品 importer 产生的 film OTIO 包。不是 Work 逆向导入，不自动采用 Storyboard，也不宣称可采纳往返已完成。

## 操作与边界

用普通 Python 启动受控新 Blender 进程：

```sh
python tools/editor-adapters/blender_cut_readback.py --host edited.blend --package exported-package --output new-saved.otio
```

入口在加载前后比较原生文件摘要，进程禁用自动脚本；子进程也核验期望摘要，发布前重验包。文件不稳定、包/素材身份变化即拒绝。它不是宿主锁或 CAS，不声称能防范改回原字节的 ABA 竞态。直接调用内部 bpy helper 不等于受控加载认证。

只读选定场景和原有 MOVIE/SOUND 实例；保留稳定 ID、资源和轨道。只允许原导出窗内裁短以及连续配对顺移，不接受扩展到未导出源窗、留白、重排、增加/删除实例。音频保持原 OTIO 样本率，帧换算后不是整数样本则拒绝，不静默取整。源码中的原音与视频对必须保持源窗/目标窗一致。

颜色处理、变换、裁剪、反放、retiming、修饰器、声音偏移/音量/声像、mono、场景动画/合成器、frame step/time remap、静音轨和输出规格改变等均在支持范围外，拒绝而非丢掉。固定版本和默认处理断言只是此受限宿主子集，不代表任意 Blender 工程都能忠实交换。导入器原有不支持字幕/效果/分数帧率的边界不变。

输出使用同目录临时文件、fsync 和独占硬链接发布；写入失败不发布半份目标，不覆盖现有文件。stdout 回执含原生工程及 OTIO 摘要，应随快照作为 companion 保存。后续复用已有 `otio_readback.capture_saved_snapshot`（明确 `media_root` 指向原包）和 `propose_saved_readback`，不得把桥接成功当成下游许可或采纳成功。原生工程若后来改动，需要重新受控读回；既有提案实时检查的是保存 OTIO，不是活跃 Blender 状态。

## 本轮实际验收

新建测试工作区绑定真实 ToS 原片，产品 importer 新建工程。源来源 https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov ，署名 (CC) Blender Foundation | mango.blender.org，CC BY 3.0 https://mango.blender.org/sharing/ 。素材未入仓，没有下载额外素材或访问用户电脑。

- 原片 25–27 和 55–57 秒，两组原视频/原声硬切；新进程读取未改工程，既有提案输出 **NO_CHANGES**。
- 首组 48→36 帧，后组开始帧 49→37、保持 48 帧；保存退出再由 launcher 重开。读回为 25–26.5 秒、55–57 秒，完整捕获快照并运行三方提案。
- 提案正确报告两轨 `HOST_TRACK_END_REQUIRES_EXPLICIT_MAPPING`，状态 **CONFLICT**，可采纳变化为零。没有降低已有门槛：84 帧总长度需要显式下游 Storyboard 映射与复验。Story­board、state、源清单字节未变。
- 实际新工程宿主渲染输出 84 视频帧 / 3.5 秒，完整解码无错误。AAC 音轨 3.52 秒，不能声称样本级无损或完全无尾 padding；未连续观看、未听审，非故事/创意质量验收。
- 11 个实际宿主内存负例确认 frame step、场景音频关闭、time remap、场景音量、合成器、条带颜色/变换/裁剪、声音偏移、静音及源色彩空间改变被拒绝。负例没有保存覆盖原生文件。
- 适配器测试 42 通过（新增 24 + 既有 18），包括 44.1/48 kHz 原时钟保留与非整样本拒绝；另有独立 atomic/launcher 探针。它们不是新听审或全量回归替代。

早期验证曾把音频 time range 错写成视频帧率，未改工程都被既有解析拒绝。已修复保留原样本率并新增回归；旧 CONFLICT 结果保留，不算最终通过。首轮默认属性假设也曾被真实宿主拒绝，最终按 4.3.2 实际默认值限定。

**本批成果是保存分支的可靠观察和保守提案桥接，不是完整可采用编辑器往返。** 下步应按既有 revision 权威，在明确授权范围内实现 Storyboard 映射，再运行 pre/post QC；不能通过忽略 CONFLICT 直接修改真源。

## 显式绑定的成对源窗扩展（实验）

默认仍拒绝 `HOST_WINDOW_EXTENSION_UNSUPPORTED`。可选 `--extension-scope /absolute/scope.json --extension-scope-sha256 <sha256>` 仅扩大已保存源窗的可观察范围，不代表编辑批准或自动采用。scope 必须绑定该保存 `.blend` 和原包摘要，逐稳定实例声明原源窗、目标源窗、目标起点和原资源 SHA：

```json
{"schema":"blender-bound-extension/1","package_sha256":"64位小写摘要","host_sha256":"64位小写摘要","instances":{"稳定实例ID":{"source_sha256":"原资源摘要","before_start_frame":600,"before_end_frame":1008,"start_frame":600,"end_frame":1080,"target_start_frame":0}}}
```

帧数为整数，源与目标起点从0开始，区间半开，帧率沿封存包；每个实际扩展的 Video 和 linked Audio 都须独立列出，且同源同窗同位置。声明实例必须恰好等于实际扩展集合。新源窗必须包含原源窗，不支持一端裁短同时另一端扩展。其余旧裁短和自然顺移规则不变，未声明源身份、轨道、处理和顺序变化继续拒绝。

终点同时受封存 `frame_count`、当前 probe 的对应流 `duration_ts*time_base` 约束；音频另核 `duration_samples`，且原OTIO采样时钟必须精确整样本。未知实际时长拒绝，不把通用素材duration当音轨完整性。原包源文件身份仍前后核验；这不是逐帧内容、音频听感或边界语义认证。

launcher 核验scope字节SHA、复制同字节到临时隔离输入，子进程绑定host SHA、校验前后scope，最终发布前父进程再核原scope及host/package。回执携带scope和SHA，应作为快照 companion 与原生工程读回回执保留。后续 `capture_saved_snapshot`、三方冲突及 `apply_host_boundary` 的当前明确批准 BoundaryProposal、完整投影和原事务门槛均不改变，不以此scope代替批准。

### 真实有界扩展证据与未采用原因

本批另行隔离复制 stage13 的真实 ToS25–42秒技术工作区，不覆盖原工作区或此前两窗测试包。新导出包在 Blender4.3.2 实际导入、保存、受控重开读回；未改分支封存后的三方提案为 `NO_CHANGES`。

- 实际另存只裁视频至40.25秒、完整保留25–42秒原声的工程，读回拒绝 `HOST_AUDIO_VIDEO_DESYNC`，没有发布OTIO。该失败保留，不用移除音频绕过。
- 实际另存声画配对25–42→25–45秒工程。显式scope精确绑定两个实例的原600–1008帧、新600–1080帧、输出起点0、原资源/包/保存工程SHA。受控重开与扩展读回成功，完整保留原17秒源窗并追加3秒，输出观察长度480帧。未渲染这个宿主工程，不冒称完整视听验证。
- 保存OTIO与scope/readback回执作为companion封存；三方提案保留4项host-only变化及两轨 `HOST_TRACK_END_REQUIRES_EXPLICIT_MAPPING` 冲突。此处只是可核验待采纳变化，不是已采用。

实际查看源25–45秒的2fps联系表及切点图，观察到人物对话画面→机器人图→文字 `40 YEARS LATER`。英语ASR与官方字幕尾句存在差异，不据此裁对白，也不把稀疏图观察当完整听审。

另建明确标识的隔离准备基线，仅补25–42源窗一致的高光引用关系，并将25–45的真实稀疏视觉观察及未知写入02/03；保留原候选零置信、原计划、所有原声与范围门槛。Agent作出的范围判断仅是“保留全部原窗并追加可见时间跃迁上下文”，不是用户具体剪点批准、听审或完整剧情判断。原 `prepare_boundary_revision` 实际运行后返回 **`SELECTION_CHANGED_REPLAN_REQUIRED`**：既有候选confidence=0，原阈值0.62，不人为提分。

原声比例1.0超出现有0.25–0.45约束、技术事件图为空不能证明hook eligibility，是源码/当前配置核查发现的后续限制；本次prepare先在选池变化处停止，不能声称后两项也是此次实际抛出的错误。没有降低门槛、编造事件、拼凑旁白或强行执行采用后QC。原stage13和准备操作前后的隔离输入摘要均保持。

完成的是**真实素材成对扩展保存→身份绑定读回→待采纳提案**。纯原片技术夹具不是完整影视解说作品；其原事务采用与采用后QC仍未完成，需独立设计符合产品定位且有真实内容证据的作品。默认拒绝行为、旧失败、未知/低置信证据保留。作者38项定向与独立11项对抗检查已通过；最终整体验证另绑定提交报告。

## 独立 PCM 旁白轨（实验，stage21）

此前 importer 将所有资源当作带画面的源素材，合法的纯音频旁白也会触发 `MEDIA_CLOCK_UNSUPPORTED`。现在仅对明确 `kind=narration`、`narration:` 资源与 narration 音轨接纳独立 PCM S16LE。核对封存摘要、唯一音频流、实际采样率/声道、起点0、实际样本总数及整数样本边界；不伪造视频尺寸或帧率，不放宽原素材检查。其余压缩编码、隐含视频、资源替换和错误角色仍拒绝。

读回仅允许旁白随同一 segment 的未裁剪画面整体顺移；不允许独立移动、裁剪、变速、换音或改变对应画面源窗。原有显式 audio Gap 可随经过配对核查的画面目标位置调整；不允许新增/移除空隙、尾随空隙。原声与视频仍逐实例同源同窗。

云端真实 Blender 4.3.2 证据：完整许可中文 FLEURS 录音（原294080个16k样本，尾补1920个静音样本使24fps边界对齐，前缀字节不变）搭配明确合成画面。实际导入、保存、新进程重开读回成功；首段原视频/原声48→36帧，后续444帧画面与旁白49→37帧顺移后再次保存、重开、读回成功。未执行 Storyboard 自动采纳，也不是影视旁白或TTS验收。

宿主混音20秒时间线输出960512个48k样本，多512样本；重采样至16k后，1.5秒预期位置录音相关系数0.998475。此为真实音频路径及位置证据，不是样本级无损、精确时长成片或人工听审。镜头理解、真实电影旁白、GUI操作和最终故事质量均未由该夹具证明。真实TTS此前因TLS证书链错误失败，未通过关闭验证或自动重试绕过。
