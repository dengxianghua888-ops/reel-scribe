# 影视选材与局部修改：只读预览

`revision-preview` 读取已有影视工作区，按 Beat 展示候选检索、分镜引用、已有渲染消费记录及局部修改范围。它是 JSON 检查入口，不是播放器，也不生成新视频。

## 使用方式

在安装影视子包的环境中执行：

```sh
douyin-film-recap revision-preview /existing/work
douyin-film-recap revision-preview /existing/work --beat-id beat-1 --beat-id beat-2
douyin-film-recap revision-preview /existing/work --base /existing/base.json
douyin-film-recap revision-preview /existing/work --proposal /existing/local-proposal.json
douyin-film-recap revision-preview /existing/work --raw-cards /existing/raw-cards.json
douyin-film-recap revision-preview /existing/work --format html > /outside/work/review.html
```

默认将 `film-revision-preview/1` JSON 输出到标准输出。命令不初始化工作区、不创建锁、不写状态或派生产物，不调用模型、TTS、FFmpeg 或原声提取。若需保存报告，由调用方明确选择工作区之外的文件；不要覆盖原有作品文件。

`--format html` 将同一预览结果输出为中文只读评审页，可以保存到工作区之外并离线用浏览器打开。默认 JSON 接口不变。评审页不加载远程字体、脚本、图片或视频，不自动读取或播放引用的源媒体，也不提供采用修改的按钮。页面中的来源路径、哈希、字幕和旁白可能属于私有材料，分享报告前需确认接收者与授权范围。

评审页提供按 Beat 定位、折叠详情和清晰的记录／声明／未知标签；材料正文不是经过本工具认证的事实。报告生成后是静态快照，无法感知工程随后发生的变化；修改后必须重新运行预览，不能拿已打开的旧页面证明当前版本仍有效。

`--base` 接受已有的 `revision-snapshot` 结果；`--proposal` 接受已有 `revise` 局部候选（`base`、`artifacts`、`scope`，以及可选 `kind`、`reason`），二者不能同时提供。候选必须只包含 `09_storyboard.json`，不接受边界或旁白专用修改请求。`--raw-cards` 是已存在的 RawEvidenceCard 数组，不会创建或提取原声。

## 如何读结果

- `candidate_pool`：记录的候选集合。进入候选池不等于被分镜使用，更不等于出现在成片中。
- `beats[].retrieval`：已有 R1 词法检索排序、淘汰与预算记录。R0 不伪装成 R1；缺失证据明确为 unknown。跨集事件覆盖和叙事完整性仍须判断。
- `storyboard_references`：当前或候选分镜引用，包括保护声明、未知扩展字段与内容哈希，不改写原始文档。
- `render_consumption`：仅在既有渲染计划、分镜、来源、音频及输出字节等绑定一致时展示 recorded；缺失、过期或不一致时为 unknown。候选未渲染，始终不继承旧成片消费记录。
- `raw_evidence`：只展示原声卡声明和与分镜的时间重叠。未重新解码原声资产，也不证明台词、声音或事件完整性。
- `scope_check`：复用已有局部修改规则的部分检查，不是采用资格。`adoption.status` 仍为 not_validated；实际采用继续使用 `revise` 或对应专用命令。

## 一致性与验收边界

读取前后比较已有版本快照与额外渲染产物字节身份；发现作品、来源、音频或代际变化时拒绝混用旧结果。此机制不锁住其他编辑器，也不保证检测读取期间变化后又恢复原字节的操作。

预览不重新解码媒体，不继承语义、声画或 QC 结论，`qc_status` 始终为 `NOT_RUN`。recorded 只表示已有消费记录的绑定通过本次检查，不表示当前成片可播放、效果合格或已经通过真实用户验收。后续采用和渲染仍遵循原有工作区、局部修改与 QC 合同。
