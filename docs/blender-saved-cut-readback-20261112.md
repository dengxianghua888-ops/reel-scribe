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
