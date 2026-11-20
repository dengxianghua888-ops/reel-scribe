---
name: work-render
description: 渲染本地作品库的指定版本，将已明确的片段、锚定音轨和字幕统一映射到成片并绑定回执；不自动实现风格标签、不做创作判断、不宣称编辑器工程已验收。
---

# 版本绑定的作品渲染

先按[通用能力交接](../../contracts/capability-handoff.md)选择当前 Agent 可用的编辑器导出或本地执行器，确认作品/修订、输出身份和读回能力。下面的 `store`、WorkDocument 与 JSON 回执是本库本地实现的字段；其他工具可返回自身的项目版本与输出标识，不要求生成 SQLite。不能把导出成功当作内容和听感通过。

输入 store 绝对路径与 expected_version，见 [作品合同](../../contracts/work-contract.md)。原子内部调用 timeline-render、audio-mix、visual-layer-render、caption-burn、media-qc；这些依赖必须可用，不绕过已有参数检查。

使用开始时的完整快照，片段/字幕/音轨/visual_layers来自同一版本。运行结束重读当前版本：`current_at_finish: false` 表示有效的旧版渲染，不能冒充最新版本；此时按任务需要导出最新版本。

render-binding.json 绑定作品 ID、版本、文档哈希和视频哈希；rendered-document.json 保存被消费状态，output-captions.json 保存实际字幕映射。style_bindings 仅记录已采用卡与参数，实际效果必须写入剪辑/音轨/字幕等字段，不能靠换 style_id 就声称已换风格。

当前支持一条拼接主画面、片段增益、作品调色段（时间线之后按片段帧区间分层套用，随后用 color-consistency-check 比较调色前后的画面，声明的保护项或上限被破坏时中止，见[作品调色合同](../../contracts/work-color-contract.md)）、已有音频、显式静态矩形视频叠层和字幕烧录；调色在叠层与字幕之前，叠层在字幕之前渲染，映射写入output-visual-layers.json。见[叠层合同](../../contracts/visual-layer-contract.md)。不支持NLE特效、跟踪或动态风格执行。输出技术通过仍为 DEGRADED，复杂层需完成内容、画面和听检。

## 不提交的完整候选预览

本地 Work 可用 `operation=work-render`、`store`、`expected_version`、`preview_candidate={path,sha256}` 请求预览。候选文件必须是 `work-candidate/1`，其 `base_version` 和 `base_document_sha256` 对上当前正式头，`revision_diff` 重新核对修改范围。渲染消费候选的**完整 WorkDocument**，复用正式渲染的主轨→调色→混音→视觉叠层→字幕→QC 顺序；`rendered-document.json` 与 `render-binding.json` 记录候选文档/输出身份和 `CANDIDATE_PREVIEW_NOT_COMMITTED`。不写 Work store，不提交再恢复，不更新交付指针。

预览期间若正式头变化，`current_at_finish=false`；该视频是旧基线候选，不可据此直接采用。后续采用仍要重新读取最新头，合并冲突并走显式 commit。缺叠层、配乐、字幕或技术检查的输出不能称完整候选预览；具体画面与声音效果仍需人工看听。无 `preview_candidate` 的旧请求保持正式版本渲染语义。
