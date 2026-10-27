# 生成任务与通用文本模型接口

`generation-task` 使用本地 SQLite 保存预算、任务、费用预留、提交边界和事件。请求均含 `operation`, `action`, `store`；`store` 必须为绝对路径。动作及额外字段以 [派发代码](../runtime/generation_dispatch.py)的 `FIELDS` 为准。`task-create` 固定 `idempotency_key`、provider/model、kind、payload、预算上限和 Work 版本绑定；同键不同意图拒绝。

`submit` 在调用提供商前持久化 `SUBMISSION_UNKNOWN`。响应丢失、超时和崩溃后不能自动再次提交；`poll` 只在提供商支持同键或已知任务 ID 查询时使用，单纯 `NOT_FOUND` 不解除不确定状态。无查询能力则停在待人工核对；取消先记意图，有取消能力才调用适配器，之后仍需查询终态。服务端硬费用封顶、同键查询、任务 ID 查询和取消均为独立能力分支；缺少硬封顶时最大费用只是本地预留，实际费用可未知并保留预留。当前未注册真实媒体 ProviderAdapter，付费 `submit/poll/cancel` 返回 `PROVIDER_ADAPTER_NOT_CONFIGURED`。

成功结果须通过 `result-record` 核服务输出身份、回执和本地文件哈希；随后用 `review-record` 绑定包含 `generation-candidate-review/1`、`ACCEPT` 或 `REJECT`、理由、候选哈希、输出 ID、结果及回执哈希的明确评审记录。`adoption-gate` 再核当前 Work 版本、候选、完整输出链和评审哈希，只返回 `READY_FOR_WORK_VERSION_CAS_ONLY`；真正采用须由现有 `timeline-revise` 校验并以 `work-version commit` 的 CAS 提交。任务成功、文件存在与评审记录都不表示已交付。

提供商成功且有输出时，必须先保存原始服务响应文件及 SHA-256，并记录 provider task ID、output ID 和可选服务端输出 SHA-256；缺身份时保留 `OUTPUT_UNKNOWN`，不能凭任意本地文件进入 `AWAITING_RESULT`。`output-attempt-begin` 接受 `task_id`、`attempt_key`、`source_kind`（`provider-download` 或 `explicit-import`）与非空 `source_ref`，只对已冻结的同一 output 记一次 `STARTED`；`output-attempt-fail` 以 `error_code` 记录失败，`output-attempts` 读取历史。重取输出建立新 attempt，绝不再次 `submit`。

`result-record` 接收 `receipt_path`、`receipt_sha256` 而非任意文件路径。`generation-output-receipt/1` 必须绑定 attempt key、task/provider/job/output ID、响应哈希、可选服务摘要、来源类型/引用、结果绝对路径与文件哈希；任务核当前尝试及全链才转 `VERIFIED`。无服务摘要时标 `LOCAL_FIRST_BASELINE`，有服务摘要且一致时标 `PROVIDER_SHA256`。`generation-candidate-review/1` 还须绑定结果回执 SHA 和 output ID，采用前重核响应、尝试、回执与媒体文件。真正 HTTP 下载和服务响应解析需由选定媒体 Provider 适配器实现；显式导入仅是操作者对来源的声明，不是服务认证。

媒体任务终态费用未知时保留预留。`billing-events` 读取该任务的账单事件；`billing-record` 另需 `task_id`、不可复用的 `event_key`、绝对 `evidence_path` 和 `evidence_sha256`。证据 JSON 使用 `generation-billing-evidence/1`，绑定 task ID、意图哈希、provider、model、币种、实际微单位费用及非空来源引用。首次结算释放预留并登记实际费用，后续修正只记差额，同键重复调用幂等；改写旧证据或同键换内容拒绝。凭证真实性须独立核实，哈希只绑定本地文件。服务端硬封顶违约会阻断 Work 采用，不能被本地账本更正静默放行。

费用以非负有符号 64 位整数微单位保存。`poll` 的终态费用累计若超出 `2**63-1`，返回 `BUDGET_ACCOUNTING_OVERFLOW` 并回滚本次任务状态、事件和预留释放；此前其他任务已成功登记的费用不回滚。后续可查询修正后的有效观察，不重新提交生成任务。本规则防止 SQLite 把溢出整数运算转为浮点数，不自动修复历史损坏账本。

`model-text-deepseek` 是独立的通用文本/function 接口。它支持 `budget-create`、`prepare`、`read`、`result`、`settle-cost` 和显式 `send-once`。`prepare` 通过绝对 `body_path` 与 `body_sha256` 读请求，避免将原文写入 operation request；内容写入权限受限的本地账本，并冻结提供商、端点、模型和请求。模型名由请求体指定，function tool call 只作为未信任数据返回，不执行工具。`send-once` 仅用官方 DeepSeek 端点和 `DEEPSEEK_API_KEY` 发起一次 Chat Completions 请求；调用前账本先记未知提交，之后不自动重试。自定义端点须由上层单独注入显式密钥和 `TextModelRegistry` 客户端，不继承官方环境密钥。`settle-cost` 用账单证据文件哈希、调用身份和幂等事件键进行显式结算或更正；证据真实性由调用方另行核实。其费用预留只有本地记账作用，不构成服务端硬上限，也不属于 W14 图像/视频生成 Provider。发送是付费动作，需单独明确授权和预算；本库未发起任何实网调用。

`model-text` 是配置式文本/function Provider 入口，旧 `model-text-deepseek` 继续可用，但两套账本不自动迁移。默认 `deepseek-default` profile 使用官方 `https://api.deepseek.com`、`deepseek-flash` 与 `DEEPSEEK_API_KEY`；宿主可用 `EDITING_TEXT_PROVIDER_PROFILES_PATH` 指向绝对 JSON 文件，格式为 `{"schema":"model-text-profiles/1","profiles":[{"profile_id":"team-provider","provider_id":"team-provider","endpoint":"https://provider.example/v1","model":"configured-model","credential_env":"EDITING_TEXT_PROVIDER_API_KEY","allow_custom_endpoint":true}]}`。文件只含环境变量名；密钥值由宿主单独配置。自定义 HTTPS 端点必须显式允许，且不得接收 `DEEPSEEK_API_KEY`。profile 的提供商、端点、模型、密钥变量名与许可标记共同绑定哈希。

`model-text/profile-list` 返回公开 profile 与哈希；`budget-create`、`prepare`、`read`、`result`、`send-once`、`settle-cost` 均由 [派发代码](../runtime/model_text_dispatch.py)校验精确字段。`prepare` 必须给出 profile ID/哈希、绝对 `body_path`/SHA-256、预算键与微单位预留；正文包含 `messages` 与 `max_tokens`，可带 function `tools`，模型与端点只能来自冻结 profile。`send-once` 在发出 HTTP 前持久化 `UNKNOWN_SUBMISSION` 和预留，未知结果不自动重试；返回的 function call 只是数据。`settle-cost` 的 `model-text-billing-evidence/1` 文件需绑定 call ID、body/profile 哈希、provider、endpoint、model、currency、实际费用与来源引用。账单证据的 SHA-256 只证明本地文件未变，不证明服务商账单真实性。费用预留不是服务端硬封顶。此接口不生成图片或视频，且未进行真实付费调用。
