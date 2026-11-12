# 绑定作品局部撤销与教程产物证据链（第十二切片）

本批接续 PR #23，不合并、不部署。完整产品方案仍未完成；以下机制不代替九格真实语义、完整看听、整卡风格或用户偏好验收。

## 兼容绑定作品的局部撤销

`work-version / prepare-local-undo` 可显式提交完整当前配方、摘要及新派生配方标识。仅支持唯一 `*` 全局、由现有配方编译器表达的字幕呈现/既有音轨增益；全部映射值须仍与当前作品一致。原约束、卡与未选参数不变，候选与当前布局均重新检查；新绑定明确对应派生配方，不冒称原配方完整生效。准备不提交，真正采用仍重验最新 CAS。

多/局部/自定义绑定、映射失真、没有完整原配方、未映射字段及音轨身份变化仍拒绝；NO_OP不生成派生配方。不会清空绑定或降低约束来换取通过。详见[Work合同](../contracts/work-contract.md)。

## 教程产物检查

新增[tutorial-artifact-check](../atomic/tutorial-artifact-check/SKILL.md)，绑定实际本地文件与声明的步骤/结果/检查窗口；复用教程前置依赖，检查源与输出双时轴，文件末次复核。结果文件为null正常返回INCOMPLETE，而非后台失败结论。

LINKAGE_VALIDATED仅表示文件字节与声明关联通过。截图产生来源、观察文字、操作因果、服务端持久化始终未认证；即使传入一句错误的“已保存”，通过只核时轴而非这句话真假。不新增统一发布门槛，不修改Work、不下载文件、不生成媒体。详见[合同](../contracts/artifact-check-contract.md)。

## 冻结机制与独立复核

- local_undo.py SHA256：`76277bc48fbdffa40d0ed14bcb778c1405918327cec68170f4bf7824c49c5376`。
- artifact_check_ops.py SHA256：`01c3408af0e55d7d173de021759c176f6a3f9e0461ff7ff43676cc1708bdba3f`。
- 绑定撤销作者38项与独立6项共44通过；含伪配方、约束、派生摘要、候选布局失败与过期采用拒绝。布局单测中替身只验调用与失败传播，不是真实排版验收。
- 产物检查作者27项与独立8项共35通过；含文件变化、伪认证字段、NaN、缺文件、任意观察文字不得提升后台认证。
- 集成定向89通过，包括上述作者测试、依赖分支和MCP入口；这些与前述测试重叠，不能相加称独立覆盖。

最终提交的完整回归和远端CI须另绑定确切SHA，不继承此前阶段绿灯。

## 真实绑定撤销验证

使用 Nikkimaria 的 CC BY-SA3.0 [历史 wikEd 教程](https://commons.wikimedia.org/w/index.php?title=File:WikEdtutorial1.webm&oldid=1131672871) 既有6秒显式归一化派生，不是原WebM直通。派生源SHA `3d3642c4aa00637ec3da0447a21b9e11d0391d68a7330143ad6fbe9a98710791`。独立新Work：24字号→字幕专用配方28→后改未绑定音轨gain与备注→显式派生撤销24。安全带、卡、未选参数与内容保持；准备和后续渲染不提交，当前sequence/version/docSHA不变，源文件SHA不变。

派生配方再交既有compiler生成独立对照候选，文档完全相同；三份输出完整解码，undo/control视频SHA均为 `f1b4c212fd444fd7a11576dc42f67f38157837ebe634bb1f3abe302e392a9b6d`，RGB/PCM逐字节相同。current28与undo24画面不同，PCM同为 `840b2db07500d7b6f9d8447796df445a8fd23816f0cb9460a75930df97b45a7c`（2,310,144字节），只说明当前混音未变，不是未混音原声不变。示范额外同源音轨是数值管线测试，不是推荐配乐。

真实负例：过期头、错误recipe摘要、100px布局越界、先修改已绑定gain使绑定失真，均拒绝。29份操作回执分别与冻结45个runtime文件一致。首次独立负例脚本误读主store的版本导致正确CAS拒绝；仅修scratch脚本并重试已知未发生的编辑，非runtime缺陷。

实际查看current/undo两张2秒抽帧：中文演示字幕在独立底带变小，网页内容一致；中文为示范标注不是原声转写。结果与第十一切片相同内容同SHA是新绑定机制保持输出的预期，不包装为新创意。完整看听/偏好验收仍NOT_RUN。完整本地证据为 `reel-stage12-bound-undo-evaluation/report.json` 与 `runtime-audit.json`，视频和素材不入源码包。

## 真实产物链验证

同一许可原WebM首次仍被`SOURCE_VIDEO_RANGE_UNVERIFIED`拒绝，保留失败回执，不宣称原片直接通过。未采用一个仅有README、缺精确转换回执的旧24–64秒派生；本批重新显式归一化原44–61秒，记录命令、源SHA与共享时钟映射，17秒有损派生完整解码通过。

实际逐张查看派生0/4/15/16秒帧，分别见wikEd未勾、已勾、带多排工具栏的着色编辑页、同编辑页；不是连续点击或保存确认。使用PNG本身作为“截图产物”正例只验证LINKAGE；真实后台结果产物缺失时null返回INCOMPLETE。错误产物SHA及早于结果的检查窗口分别拒绝。没有为获得成功而将截图冒充后台保存文件；action字段明确只是已勾状态锚点，不捏造看见点击。

四份回执与45个冻结runtime文件一致，原源SHA未改、没有Work操作。另独立复现旧原片49.503/59.003/113.003三帧的字节与PTS，只对这三帧提供重现证据；原子报告仍如实保留FRAME_DERIVATION_NOT_VERIFIED，不推广为任意截图都已认证。后台事实与观察真伪均未认证，未听审。

本地完整记录：`reel-stage12-artifact-evaluation/normalized-final/report.json`、`explicit-import/receipt.json`、`reproduced/report.json`及README。素材不入仓，派生对外分发须保留Nikkimaria归属/来源/修改说明及[CC BY-SA3.0](https://creativecommons.org/licenses/by-sa/3.0/)。
