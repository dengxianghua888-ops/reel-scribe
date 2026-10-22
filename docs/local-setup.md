# 本地接入

这是实验性源码的检查入口，未宣称完成任何特定客户端的安装验收。先从仓库根执行：

```bash
python3 scripts/verify_library.py structure
python3 scripts/install_doctor.py --root "$PWD"
```

Python 3.9.6 仅是通用库历史开发记录，不是整库支持声明；影视子项目要求 Python >=3.11。当前自动化目标为 Ubuntu / Python 3.12；分层支持与未验证平台见 [支持矩阵](support-matrix.md)。Skill 文本与注册读取不要求媒体依赖。FFmpeg／ffprobe、字体、Pillow、NumPy、ASR 等按具体操作条件使用，以诊断结果和对应合同为准，不必一次安装所有依赖。

## MCP

客户端启动命令为 `python3`，参数为本仓库 `scripts/mcp_server.py` 的绝对路径，传输方式为 stdio。服务通过标准输入输出交换 JSON-RPC；直接运行后等待输入属于正常行为。

请求信封必须包含 `jsonrpc: "2.0"`、字符串 `method`，以及字符串或整数 `id`；布尔、浮点和 `null` 不作为 MCP 请求 ID。通知省略 `id`。有合法 ID 的无效信封返回 `-32600`；不能关联合法 ID 的解析错误、非对象或非法 ID 仅在 stderr 写固定诊断，不回显输入内容，也不向 stdout 写含 `id:null` 的协议包。后续合法请求继续处理。这是本地 MCP 的受限处理策略，不是完整通用 JSON-RPC batch 或客户端互操作验收。

工具：

- `list_skills`：列出本地注册；不执行媒体操作。
- `diagnose_installation`：报告本地依赖，可传入具体 request 检查对应分支。
- `run_operation`：接收明确的 runtime request，写入新的独占工作目录。

工具通过 `tools/list` 显式声明四个布尔注解，按 [MCP ToolAnnotations 规范](https://modelcontextprotocol.io/specification/2025-11-25/schema#toolannotations) 描述实际处理器：

| 工具 | readOnlyHint | destructiveHint | idempotentHint | openWorldHint |
| --- | --- | --- | --- | --- |
| `list_skills` | true | false | true | false |
| `diagnose_installation` | true | false | true | false |
| `run_operation` | false | true | false | true |

前两个工具读取本地注册、绑定文件及依赖信息；诊断会运行本地工具的版本/媒体探测，不安装、下载或调用联网 Provider。只读工具的 destructiveHint 和 idempotentHint 在协议中不影响语义；重复探测的结果仍可随环境变化。

`run_operation` 的工作根目录只限制本次输出目录，不是所有副作用的沙箱：请求可修改目录外既有 Work、批处理或 Provider 账本，显式联网分支可发送付费请求。因此不能声明为只读、仅新增或封闭交互。已有输出目录会被拒绝，即使上次失败并留下部分文件；换新目录是新执行，不是通用重试或恢复协议。个别分支的事件键、版本检查或 send-once 去重，不构成整个工具的幂等承诺。调用前应核实上次 receipt、既有存储状态及具体分支合同。

这些注解仅是客户端提示，不替代权限、费用授权或验收。服务启动、`tools/list`、`list_skills` 和 `diagnose_installation` 不要求 `DEEPSEEK_API_KEY`；`.mcp.json` 的 `env_vars` 是可传递变量名列表，不是必填凭据声明。只有选定对应 Provider 的发送分支才要求其密钥；本地准备、读取、预算记账等分支不因此要求联网凭据。

执行操作前，在客户端环境中设置 `EDITING_SKILL_WORK_ROOT` 为你选择的绝对目录。每次 `work_dir` 必须是其下尚不存在的新目录。FFmpeg 与 ffprobe 可通过 `EDITING_FFMPEG`、`EDITING_FFPROBE` 指定。不要把密钥写进仓库。

`.codex-plugin/` 和 `.mcp.json` 是待验证的插件接入定义。仓库不附带已安装证明；`contracts/portable-resource-edges.md` 中的个人机器流程属于历史开发说明，不能直接复制本机路径执行。按所用客户端的实际配置方式接入此 stdio 服务。配置中的相对 `args`、`cwd` 与 `env_vars` 字段不能视为跨客户端通用格式；手动接入时使用脚本绝对路径，并按客户端支持的环境变量配置方式设置工作根目录。

## 执行器

阅读具体 Skill 及其输入合同后，才构造 request。CLI 接口：

```bash
python3 runtime/editing_runtime.py run \
  --request /absolute/path/request.json \
  --work-dir /absolute/path/new-exclusive-run
```

这是命令接口示意；仓库不提供虚构的通用 request。输出 receipt 只记录执行范围，不能替代真人视听或编辑器工程验收。

## 音频与可迁移性

本仓库保留 `runtime/rubberband_stream.cpp`，不分发开发机上编译的 helper 或 Rubber Band 二进制。有声变速默认依赖固定身份的 Rubber Band helper，因此该默认路径在本预览中尚不能直接运行。路由说明与当前实现一致：只有显式选择 `audio_backend.kind="ffmpeg-atempo"` 才使用另一后端，其证据范围不同。

当前 wrapper 含 macOS 接口，runtime 还要求 helper 身份绑定，因此不能把“任意编译成功”理解为支持该严格路径。1×、无声和明确选择的其他音频后端各按自己的合同执行；FFmpeg atempo 路径不继承 Rubber Band 路径的严格音频证据。

Provider 代码是可选执行适配。加载、路由、列举 Skill 不要求 DeepSeek，也不要求任意生成模型。若选择联网分支，凭据、费用和请求授权由运行 Agent 处理。

### MCP long operations and cancellation

The stdio reader remains available for `ping` and `notifications/cancelled`
(`params.requestId`) while tools run on one serialized execution lane. Responses
may arrive out of order; match them by JSON-RPC ID. At most 16 tool calls are
pending. Supply `_meta.progressToken` on `tools/call` for start/execution/finish
notifications; these are lifecycle milestones, not a fabricated percentage.
Cancellation is cooperative: queued runtime operations retain a FAILED cancellation
receipt, and owned media subprocess groups are stopped and reaped. A provider
request already in flight is not remotely cancelled or refunded by this signal;
its ledger/result must still be reconciled. Pure Python/provider work without a
cancellation checkpoint can finish normally. Closing stdin waits for pending
work; it is not a cancellation request.

Still-image encoding has a 120-second watchdog covering frame generation, blocked
pipe writes and encoder completion, with a maximum 36,000 frames and 30 billion
output pixels per request. Timeout/cancellation preserves diagnostics and partial
outputs; it does not certify the partial file as a deliverable.
