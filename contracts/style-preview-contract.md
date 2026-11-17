# 同内容呈现候选预览

`style-recipe-preview` 从同一个权威 Work 版本，编译并实际渲染 2–4 个明确的呈现配方。没有内容重选、自动风格推荐、自动胜者或自动提交。支持范围与 `style-recipe-compile` 相同，仅既有字幕样式参数和指定音轨的固定增益。

## 请求

- `operation`: `style-recipe-preview`
- `store`: 现有 Work SQLite 的绝对路径。
- `expected_version`: 当前 Work 版本。
- `variants`: 2–4 个对象，字段为 `id`、`recipe`、`expected_recipe_sha256`、`capabilities`、`scope`。后四项沿用配方合同。ID 仅字母数字开头，后续可用字母数字、下划线、连字符，总长不超过 64，不可重复。
- 可选 `audio_backend`、`source_consumption` 仅显式透传现有 Work render 合同；不替用户选变速后端、改默认消费策略或隐式付费。

运行器须使用新的输出目录。所有候选先编译，任一配方不合法不会启动渲染。每个候选绑定同一个 `base_version` 和 `base_document_sha256`；源计划、字幕内容/时间、证据保护不改。

## 成功产物

- 每候选的 `variants/<id>/compile/candidate.json` 与配方参数映射报告；真实视频、渲染绑定和操作回执保存在 `recovery-batch/jobs/<id>/attempt-XXXX/`，以 manifest 中的摘要绑定路径为准。
- `style-preview.json`：固定候选、视频、回执摘要，实际参数对照及基线身份。`PREVIEWS_RENDERED_NOT_COMMITTED` 不是内容/风格/听检/原生编辑器验收。
- `comparison.html`：纯本地视频对比页，无网络依赖和脚本，只引用输出目录内的视频相对路径；不自动选择胜者。保留整个目录才可播放。

编译器不改当前 Work。渲染前后与整组结束均重核当前头，结束还检查原素材、卡片及产物哈希。发现过期、素材变化或任一候选失败时不生成成功 manifest 或最终比较 HTML；已经生成的独立候选/视频/失败回执保留用于诊断，不视作全组成功。最终“当前”只是最后观察时刻，采用前仍须 Work CAS 重新核版本和范围。

## 恢复衔接

所有配方成功编译后、渲染前会保存 `batch-prepare-request.json`。该文件是现有 `work-batch-render prepare` 的请求，携带精确候选 SHA、版本及显式音频/素材消费选项。批次已建立时需要恢复应使用保存的 batch run/status 和完整性/重试合同，不对同目录再次 prepare，不另建缓存账本。本操作首轮渲染即通过现有 batch prepare/run 执行，已成功的候选进入同一完整性账本。`batch-resume-request.json` 记录相同 manifest 摘要，默认 `retry_failed: false`；明确选择重试失败项时才改为 true。有效成功候选经复核可复用，失败项单独重试。通过 batch 恢复的视频不会自动重建本操作比较 HTML 或令先前失败调用变成功，须检查实际 batch 产物。

测试的合成色块和正弦音频只证明技术闭环；真实素材适切性、字幕遮挡、语义正确性、响度听感、风格辨识和编辑器往返需另验。
