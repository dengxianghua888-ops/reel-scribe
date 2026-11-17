# 全仓库代码审查（2026-11-17）

基线：`46a5612`（main，PR #22 合并后）。范围：`runtime/`、`scripts/`、`atomic/*/scripts`、影视解说子集
`workflows/raven-film-recap/douyin-film-recap/src`，以及 CI、注册表、清单和文档一致性。审查只处理代码与
接口行为，不评价剪辑效果，也不构成真实素材、编辑器或用户链验收。

## 基线结果（修改前）

- `scripts/verify_library.py structure`：PASSED，2044 条本地链接，0 错误。
- 顶层 `tests/runtime tests/packaging tests/drama`：334 passed。
- 影视子集：`validate_skill.py` 通过；pytest 全部通过（约 25 项因可选依赖跳过），
  有 PySceneDetect `get_seconds()` 弃用警告和一条测试内 Pydantic 序列化警告。
- `ruff --select F821,F822,F823,E9`：通过。扩大到 `F,B` 后多为测试 fixture 与“循环内立即调用的闭包”误报，
  另有 25 处未使用导入（未在本次清理）。

## 已修复

| # | 问题 | 影响 | 修复 |
|---|---|---|---|
| 1 | `editing_runtime.run()` 只捕获 `ContractError/OSError/KeyError/TypeError/ValueError/sqlite3.Error`。`ZeroDivisionError`、`IndexError`、`AttributeError`、`StopIteration` 等实现缺陷会直接逃出。 | 运行目录只剩 `request.json`，没有 `receipt.json` 和产物清单；MCP 只返回一句裸异常文本。已用原代码复现。 | 增加兜底分支：写入 FAILED receipt（`INTERNAL_ERROR: <类型>: …`、`internal_error: true`）、`internal-error-traceback.txt` 与完整产物清单。 |
| 2 | 含 NaN/Infinity 的请求先建目录，随后 `write_json(allow_nan=False)` 才失败。 | 留下空目录，同一路径无法重试。 | 先计算请求指纹，非 JSON 值在建目录前以 `REQUEST_JSON_INVALID` 拒绝。 |
| 3 | `color_ops` / `overlay_ops` / `reframe_ops` 直接用 `Fraction()` 解析 ffprobe 帧率。ffprobe 对未知帧率报告 `0/0`，这会抛 `ZeroDivisionError`。 | 本该是 `*_CFR_REQUIRED` 合同错误，却成了未归类异常（见 #1）。 | 新增 `frame_rate()`，`0/0`、缺失或格式错误一律视为 0，交给原有的范围检查；输出端校验（render、still、reframe）同样改用它。 |
| 4 | `cue_ops`（标记）、`multicam_ops`（同步证据）、`localization_ops`（源稿）和 `asr_ops`（模型锁、环境锁）先用 `source()` 哈希文件，再按路径重新读取并解析。 | 实际解析的字节没有和已验证的哈希绑定。#18–#22 已在 Work、batch、文本见证中修过同一类问题，这几处是遗漏。 | 新增 `verified_json()`：在同一个有界缓冲上完成哈希和解析（UTF-8，32 MiB 上限），上述 5 处改用它。 |
| 5 | 影视渲染 `_escape_subtitle_path()` 用 `subtitles='…\'…'` 包裹路径。FFmpeg 单引号内的反斜杠是字面字符，此外还会把 POSIX 路径中的 `\` 改成 `/`。 | 工作目录含撇号（如 `~/Movies/John's project`）或反斜杠时，字幕烧录失败。已用真实 FFmpeg 复现。 | 改为不加引号的两级转义：先按选项值转义 `\ ' :`，再按滤镜图转义 `\ ' [ ] , ;`。`subtitles`/`fontsdir` 对 `' : , [ ] ; \ % =` 和空格均已用真实 FFmpeg 验证。 |
| 6 | 开启 `story.allow_external_context` 且配置了 `project.context_file`，但文件不存在时，故事阶段静默按“无上下文”调用模型。 | 违反影视子集 AGENTS 第 6 条“不得静默降级”，并产生付费请求。 | 在发送任何模型请求前抛出 `FileNotFoundError`。 |
| 7 | PySceneDetect 0.7 已弃用 `FrameTimecode.get_seconds()`。 | 每次检测都有弃用警告，未来版本会失效。 | 优先使用 `.seconds`，保留旧接口回退。 |
| 8 | 影视 `doctor` 的 libass 检查包含 `"subtitles" in output`，`-filters` 输出的任何描述文字只要含该词就会判 PASS。 | 可能误报字幕烧录可用。 | 改为按滤镜名列匹配 `subtitles`。 |
| 9 | runtime/scripts 中有 30 余处 `read_text()` / `write_text()` 未指定编码，而写入端统一是 UTF-8（`ensure_ascii=False`）。 | 在非 UTF-8 locale（如 GB18030）下读取中文 receipt、注册表或清单会失败，`build_portable_bundle` 写 `external-evidence.json` 也会出错。 | 统一显式使用 `encoding='utf-8'`。 |

新增回归测试：`tests/runtime/test_review_20261117.py`（12 项）和影视子集
`tests/test_review_20261117.py`（11 项，含真实 FFmpeg 滤镜图）。
`contracts/operation-contract.md` 已同步记录 #1、#2、#4 的行为。

## 建议（本次未改，需维护者决定）

1. **模型提示中的 JSON Schema 是 Python repr**：`providers.py` 的 `chat_json` 用 f-string 嵌入 `{schema}`，输出单引号、`True`、`None`，不是 JSON。这可能诱导模型输出无效 JSON，多一次付费修复请求。建议改用 `json.dumps(schema, ensure_ascii=False)`。未改的原因：提示体变化会改变 send-intent 载荷哈希，已有工作区重算该阶段时会触发 `SEND_INTENT_PAYLOAD_CHANGED`，需要决定是否提升 `PIPELINE_REVISION` 或提供迁移。
2. **故事上下文字节未绑定**：`analysis.build_story` 消费时重新读取 `context_file`，没有和 `binding.context_identity` 对比。阶段前后的边界检查能发现大多数变化，但发现不了 A→B→A 的替换，而且远程请求已经发出。建议在管线中只读一次并校验哈希，再传入已验证的文本。`still_ops` 的 `Image.open(path)` 同样会在哈希后重读像素。
3. **帧率配置不一致**：`RenderConfig.fps: int`，而 `render_plan` 已支持有理数帧率，用户配置无法设置 `30000/1001`。测试中直接给它赋字符串，引发 Pydantic 警告。
4. **重复解码开销**：`normalize_plan` 对每个 clip 用 `ffprobe -show_frames` 观察帧时钟（会解码），并对来源做全量 SHA。`timeline-patch` 会规范化两次，`caption-map` 再做一次。可考虑在单次运行内按（内容 SHA、选择器、窗口）缓存观察结果，同时保持失败即关闭。
5. **子进程文本解码依赖 locale**：`owned_process(text=True)` 未指定编码。ffprobe 标签或 stderr 中出现非 UTF-8 字节时，会在解码阶段抛 `UnicodeDecodeError`。建议 stderr 使用 `errors='replace'`，stdout 保持严格并报出明确错误码。
6. **版本与变更记录**：`plugin.json` 和 MCP `serverInfo` 是 0.1.0，runtime 是 `0.17.0-dev`，影视包是 0.3.0，CHANGELOG 最新条目是 v0.3.0-alpha.1（写“16 条复杂工作流”，注册表现为 17 条，新增了剧情制作）。建议补充 Unreleased 段并说明各版本号的含义。
7. **MCP 协议协商**：客户端请求未知版本时回退到 `2025-03-26`。规范建议回退到服务器支持的最新版本（这里是 `2025-06-18`）。现有测试明确断言当前行为，可能是有意的兼容选择。
8. **可维护性**：`runtime/*_ops.py` 和 `batch_ops.py` 大量使用分号拼接的超长单行，审查成本高。建议对改动到的文件逐步执行 `ruff format`。CI 只检查致命 lint 子集，可在清理 25 处未使用导入后加入 `F401/F841`。
9. **CI 触发**：`on: [push, pull_request]` 会让 PR 分支重复运行全部矩阵（含 torch 安装），建议把 `push` 限制为 main。

## 已检查、未发现问题

- SQLite 访问全部参数化；DeepSeek/通用文本 Provider 不回显 HTTP 错误体，禁止重定向，并限制响应大小。
- concat 列表的 `'\''` 转义正确；工作目录与输入目录互相包含时会被拒绝。
- `analyze_target_pcm` 的纯 Python 逐样本循环实测约 0.57 s/分钟立体声音频，相对编码耗时不是瓶颈。
- B023（循环变量闭包）在源码中的命中都是同一次迭代内立即调用，不是延迟绑定缺陷。

## 限制

新增测试使用合成 lavfi 输入、伪造的 ffprobe 元数据和临时 JSON，只证明接口与错误路径行为，不证明字幕排版、
听感或真实素材效果。本次环境为 Linux / Python 3.13 / FFmpeg 6.1，未覆盖 macOS 或其他 FFmpeg 版本。
