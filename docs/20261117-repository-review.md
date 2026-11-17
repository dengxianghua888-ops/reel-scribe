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
  另有 27 处未使用导入/变量（第二轮清理，见 #17）。

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

新增回归测试：`tests/runtime/test_review_20261117.py` 和影视子集 `tests/test_review_20261117.py`
（含真实 FFmpeg 滤镜图）。
`contracts/operation-contract.md` 已同步记录 #1、#2、#4 的行为。

## 第二轮：按审查建议落实

维护者确认按建议处理，以下各项均已实现并附回归测试。

| # | 建议 | 决定与实现 |
|---|---|---|
| 10 | 模型提示中的 JSON Schema 是 Python repr | `chat_json` 改用 `json.dumps(schema, ensure_ascii=False, sort_keys=True)`。为避免已有工作区重算时卡在 `SEND_INTENT_PAYLOAD_CHANGED`，结构化请求改用 `:schema-json` 意图键命名空间。没有采用提升 `PIPELINE_REVISION` 的方案：那会让所有旧工作区的 `render-current` 被拒，并强制生成新代际。为保持“改变载荷不能掩盖 UNKNOWN 发送”的不变量，`send_guard` 新增 `superseded_keys`：旧键下仍为 UNKNOWN 的发送会阻止替代请求，直到 `reconcile-send` 核对；旧键下已成功的回复不会被重放，替代请求需要重新授权。 |
| 11 | 故事上下文与静帧字节未绑定 | 新增 `read_story_context()`。管线以 `bound=True` 读取一次上下文，并与输入绑定中记录的 SHA、字节数比对，再把同一份文本传给 `build_story`。上下文改为在任何付费分块请求之前解析。`still_ops` 从已哈希的有界缓冲（512 MiB）解码。 |
| 12 | `RenderConfig.fps` 只能是整数 | 接受正整数或精确的 `N/D` 字符串，如 `30000/1001`。拒绝 `29.97` 这类二进制浮点数。整数值仍存为整数，已有配置指纹不变。QC 的帧率与时长容差改用 `fps_rational`。 |
| 13 | 重复解码开销 | `windowed_mix_clock` 在单次 `run()` 内按（已验证内容 SHA、路径、窗口、选项、活动来源绑定、工具实例）复用观察结果，返回深拷贝。`timeline-patch` 的时钟观察次数由 4 次降为 2 次。来源字节一旦变化，仍会先在 SHA 检查处失败。 |
| 14 | 子进程解码依赖 locale | `owned_process`、`tool_identity`、影视 `run_command` 与 OTIO 版本探测统一使用 `encoding='utf-8', errors='replace'`。 |
| 15 | 版本与变更记录 | CHANGELOG 增加 Unreleased 段（含兼容性说明）。`docs/packaging.md` 增加“版本号的含义”表。各组件版本号本身不改动，以免伪造发行语义。 |
| 16 | MCP 协议回退 | 对未知或缺省的协议版本回退到最新支持的 `2025-06-18`，测试同步更新。 |
| 17 | 可维护性与 lint | 清理 25 处未使用的导入和变量，另有 2 处 pytest fixture 导入改为显式 `noqa`。CI 两个 lint 步骤加入 `F401,F841`。未对分号风格的文件做整体 `ruff format`，因为仅 `runtime/` 就会产生约 2 万行纯格式差异，会掩盖行为修复，建议单独发一个只做格式化的 PR。 |
| 18 | CI 重复运行 | 第三轮已改回：分支 `push` 测精确提交头，`pull_request` 测合并结果，两者都是本仓库 PR 的验收证据，不应去掉其一。改为加 `concurrency`：同一 ref 的新推送取消未完成的旧运行，`main` 保留每次运行；另新增 `workflow_dispatch`。 |

## 第三轮：再次深查

本轮重审了 PR #24 的每一处改动，并补看上一轮未细看的模块。PR 上的 Codex 自动审查提出 1 条发现，确认成立并已修复。

| # | 发现 | 处理 |
|---|---|---|
| 19 | （Codex）`:schema-json` 迁移防护只检查同一尝试位置的旧意图。旧工作区中若 `format-0` 收到 400（记为 SUCCEEDED）而 `format-1` 超时（UNKNOWN），或旧 `json-repair` 请求为 UNKNOWN，新命名空间的首个请求仍会发出，可能重复计费。 | `chat_json` 在新命名空间的**每一次**发送前，都检查该逻辑请求在旧版本中可能产生的全部意图（主请求与 json-repair 各两次格式尝试），任一为 UNKNOWN 即阻止。两个场景都有回归测试，在修复前的提交上失败。已核对为 NOT_SUBMITTED_CONFIRMED 的意图不会阻止替代请求。 |
| 20 | 时钟缓存键使用 `id(binding)`、`id(tools)`。对象释放后 id 可被复用，“不跨消费边界”的保证因此不严格。 | 缓存条目持有这两个对象的强引用，命中时用 `is` 校验；补充模拟 id 复用的测试。 |
| 21 | 第二轮把 CI `push` 限定到 `main`，会失去分支精确提交头的 CI 证据。 | 改回，见 #18。 |
| 22 | 影视恢复包校验读取 `recover.py` 时未指定编码。 | 改为 `encoding="utf-8"`，与写入端一致。 |

本轮新增建议（未改）：

- `multicam_ops` 的同步解码直接用 `subprocess.run`，没有经过 `exec_tool`/`owned_process`，因此不响应 MCP 取消，也不写工具诊断。另外 `-ss` 位于 `-i` 之后，长录制后段的窗口每次都要从文件开头解码。改为输入端定位会改变测量的采样起点，属于测量语义变化，需要先用真实多机位素材核对偏移结果，再决定是否修改。

## 已检查、未发现问题

- SQLite 访问全部参数化；DeepSeek/通用文本 Provider 不回显 HTTP 错误体，禁止重定向，并限制响应大小。
- concat 列表的 `'\''` 转义正确；工作目录与输入目录互相包含时会被拒绝。
- `analyze_target_pcm` 的纯 Python 逐样本循环实测约 0.57 s/分钟立体声音频，相对编码耗时不是瓶颈。
- B023（循环变量闭包）在源码中的命中都是同一次迭代内立即调用，不是延迟绑定缺陷。

## 限制

新增测试使用合成 lavfi 输入、伪造的 ffprobe 元数据和临时 JSON，只证明接口与错误路径行为，不证明字幕排版、
听感或真实素材效果。本次环境为 Linux / Python 3.13 / FFmpeg 6.1，未覆盖 macOS 或其他 FFmpeg 版本。
