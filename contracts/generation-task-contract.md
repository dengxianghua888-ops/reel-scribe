# 生成任务与通用文本模型接口

`generation-task` 使用本地 SQLite 保存预算、任务、费用预留、提交边界和事件。请求均含 `operation`, `action`, `store`；`store` 必须为绝对路径。动作及额外字段以 [派发代码](../runtime/generation_dispatch.py)的必填 `FIELDS` 与显式可选字段校验为准。`task-create` 固定 `idempotency_key`、provider/model、kind、payload、预算上限和 Work 版本绑定；同键不同意图拒绝。

## 恢复、复用与重新创作是不同意图

| 用户意图 | 使用现有合同的动作 | 必须保持的边界 |
|---|---|---|
| 恢复同一任务 | 读取原 task/key，按提供商已声明的能力查询；下载失败只为同一 output 建新 output attempt | 不重新 submit，不把 `UNKNOWN` / `NOT_FOUND` 当作未受理，也不通过换 key 绕过未知提交。相同 key 和冻结参数返回同一 task；改参数不再是恢复 |
| 指定已验收 SHA 的已有素材复用 | 重新读取并核对那份素材的实际 SHA，保留原 task/job/output、原响应、原 receipt 及原评审来源；由当前作品按既有[能力交接](capability-handoff.md)与 Work 修订合同接入该源 | 不发新的生成请求，不伪造新任务的 provider receipt。原 Work 的接受意见和 adoption gate 仅属于其原候选/版本；当前 Work 仍须自己的内容评审、读回与 CAS，不能继承旧作品的采用或交付结论 |
| 相同提示词重新创作 | 记录明确的新创作意图，使用新 idempotency key 和新 task；新服务输出、回执与评审分别绑定新 task | 不是未知提交的恢复路径。提示词相同、甚至素材字节和候选文件 SHA 相同，也可能是两个真实的生成调用；以 task/job/output 和回执链区分，不能强求“新候选必须字节不同”或沿用旧 task 的评审代签 |

本账本不根据相同 payload 全局去重，也不能从自然语言自行判定操作者新建 key 是重新创作还是错误重试；运行 Agent 必须在提交前根据用户意图与未闭合任务记录作上述区分。未知原任务仍保留原身份、预留和查证缺口，不能被新任务的成功覆盖。相同字节的再次取回也必须核验此次 receipt 自身的 task/provider/job/output/原响应身份；既有 canonical receipt 核验通过不能替代新重取 receipt 的身份检查。该检查不会重写原已验证结果链。

同文件重取的快路径在核验旧 canonical 链后，再检查本次 receipt 与结果文件的 SHA，变化则返回 `RESULT_HASH_CHANGED`，不写入新的 COMPLETE attempt 或事件。它是记录边界的读回检查，不是持续文件锁或媒体内容认证。

下述 gate 只核调用方传入的当前 Work token，返回 `READY_FOR_WORK_VERSION_CAS_ONLY`；它本身不读取当前 WorkStore，也不代表已完成当前作品采用。执行者须读真实当前作品、复核候选并进行 Work-version CAS 与采用后读回。`tests/runtime/test_generation_intents.py` 的 G1–G4 使用本地 synthetic adapter、真实 SQLite 与普通合成字节；token-only断言不作真实当前工程提交证据，另列Work SQLite/CAS/readback案例使用明确声明的synthetic媒体元数据，不认证真实探测、模型质量、宿主或真人验收。

## 指定结果 SHA 的显式复用 gate

旧 `adoption-gate` 的任务 Work binding 完全保留。省略 `reuse` 时仍要求当前 Work 与原生成任务的 work_id/version/document_sha256 一致；不能把原任务挪到新Work或较新版本后冒称通过。需要把已验收源用于当前另一版本/Work时，仍使用**同一个** `adoption-gate`，额外显式传 `reuse`；不新建生成任务，不制造新的 provider receipt，不绕过gate走普通source提交。

请求原必填 `task_id,current_work,candidate_path,candidate_sha256` 不变。仅此action允许可选 `reuse`，精确字段为：

以下是字段示意，实际请求及review文件须为UTF-8 JSON对象，不能将示意中的中文说明或YAML写法直接当JSON提交。

```text
reuse: {
  intent: "reuse-verified-result",
  result_sha256: 明确选定的原结果SHA,
  result_receipt_sha256: 原canonical结果回执SHA,
  origin_candidate_sha256: 原ACCEPT记录的候选SHA,
  origin_review_sha256: 原ACCEPT记录及其实际评审文件SHA,
  review_path: 当前目标用途评审的绝对文件路径,
  review_sha256: 当前目标用途评审文件SHA
}
```

显式 `reuse:null`、多余/缺失字段、非法SHA或非法target Work三元组均拒绝，不能默默退回旧分支。`current_work` 是已从当前作品读到的target `{work_id,version,document_sha256}`；work_id及两个SHA均严格校验。当前候选继续使用原 `work-candidate/1` 五字段 `schema,base_version,base_document_sha256,document,scope`，不增加新Work格式。候选base须匹配target，document必须实际引用原已验证结果path/SHA；scope和当前真实Work冲突仍由既有Work提交端再核。

当前用途评审是独立只读文件，格式为 `generation-reuse-review/1`，精确字段：

```text
schema: generation-reuse-review/1
task_id: 原source任务ID
result_sha256: 同一明确结果pin
result_receipt_sha256: 同一原结果回执SHA
origin_candidate_sha256: 同一原候选SHA
origin_review_sha256: 同一原ACCEPT评审SHA
target_work: 本次current_work三元组
candidate_sha256: 当前目标候选SHA
decision: ACCEPT 或 REJECT
rationale: 非空、针对当前用途的理由
```

该新文件不能用旧 `generation-candidate-review/1` 代替，也不经 `review-record` 覆写原来源评审。原candidate_reviews唯一性不放宽；即使素材/候选字节相同，当前用途的不同review仍有自己的文件SHA。它记录复杂层的明确声明，不认证真人身份、真实看听或用途语义正确。

显式分支在现有SQLite写事务中重验原task/job/output/原响应/结果receipt/attempt/result全链，固定结果与回执pin，并从原candidate_reviews查原ACCEPT、核实际原review文件的task/candidate/result/receipt/output关系。新review再绑定这些原pins、target token与当前候选SHA。返回前重核来源链及原review、新review、当前候选字节；可观察漂移即拒绝，失败不改变task、预算、原reviews、events或Work头。错误区分 `REUSE_RESULT_PIN_MISMATCH`、`ORIGIN_ACCEPTED_REVIEW_REQUIRED`、`ORIGIN_REVIEW_HASH_CHANGED`、`REUSE_REVIEW_HASH_CHANGED`、`REUSE_REVIEW_BINDING_MISMATCH`、`EXPLICIT_REUSE_ACCEPTED_REVIEW_REQUIRED` 与原候选/base/来源冲突，不把失败当新生成机会。

成功只在原task_events追加 `reuse_gate_checked`，绑定原来源pins、target、当前candidate与新review SHA，保持task、预算、原结果/评审不变。相同绑定在 `BEGIN IMMEDIATE` 内按确定性key去重；重复调用/重开先完整重核，再返回同一检查身份，不重复audit或submit。同SHA的candidate/review安全迁址不改变该身份；新的合法review SHA属于新绑定。已有audit不能跳过源/证据/target复核，检查后的可写文件仍须由实际采用环节按合同读回，不能把边界SHA检查称为持续文件锁。

返回仍为 `generation-adoption-gate/1`、`READY_FOR_WORK_VERSION_CAS_ONLY`、`publishable:false`；显式结果另给原 `source_work_binding`、origin review/candidate pins和 `reuse_audit_key`，`expected_work`绑定当前target。调用方必须真实read当前Work → 形成受限candidate并评审 → gate → 原work-version commit的expected_version CAS → 采用后readback。gate不自动读当前WorkStore或移动其头；若准备后当前Work变化，原CAS仍以 `WORK_VERSION_CONFLICT` 拒绝。

`submit` 在调用提供商前持久化 `SUBMISSION_UNKNOWN`。响应丢失、超时和崩溃后不能自动再次提交；`poll` 只在提供商支持同键或已知任务 ID 查询时使用，单纯 `NOT_FOUND` 不解除不确定状态。无查询能力则停在待人工核对；取消先记意图，有取消能力才调用适配器，之后仍需查询终态。服务端硬费用封顶、同键查询、任务 ID 查询和取消均为独立能力分支；缺少硬封顶时最大费用只是本地预留，实际费用可未知并保留预留。当前未注册真实媒体 ProviderAdapter，付费 `submit/poll/cancel` 返回 `PROVIDER_ADAPTER_NOT_CONFIGURED`。

成功结果须通过 `result-record` 核服务输出身份、回执和本地文件哈希；随后用 `review-record` 绑定包含 `generation-candidate-review/1`、`ACCEPT` 或 `REJECT`、理由、候选哈希、输出 ID、结果及回执哈希的明确评审记录。`adoption-gate` 再核当前 Work 版本、候选、完整输出链和评审哈希，只返回 `READY_FOR_WORK_VERSION_CAS_ONLY`；真正采用须由现有 `timeline-revise` 校验并以 `work-version commit` 的 CAS 提交。任务成功、文件存在与评审记录都不表示已交付。

提供商成功且有输出时，必须先保存原始服务响应文件及 SHA-256，并记录 provider task ID、output ID 和可选服务端输出 SHA-256；缺身份时保留 `OUTPUT_UNKNOWN`，不能凭任意本地文件进入 `AWAITING_RESULT`。`output-attempt-begin` 接受 `task_id`、`attempt_key`、`source_kind`（`provider-download` 或 `explicit-import`）与非空 `source_ref`，只对已冻结的同一 output 记一次 `STARTED`；`output-attempt-fail` 以 `error_code` 记录失败，`output-attempts` 读取历史。重取输出建立新 attempt，绝不再次 `submit`。

`result-record` 接收 `receipt_path`、`receipt_sha256` 而非任意文件路径。`generation-output-receipt/1` 必须绑定 attempt key、task/provider/job/output ID、响应哈希、可选服务摘要、来源类型/引用、结果绝对路径与文件哈希；任务核当前尝试及全链才转 `VERIFIED`。无服务摘要时标 `LOCAL_FIRST_BASELINE`，有服务摘要且一致时标 `PROVIDER_SHA256`。`generation-candidate-review/1` 还须绑定结果回执 SHA 和 output ID，采用前重核响应、尝试、回执与媒体文件。真正 HTTP 下载和服务响应解析需由选定媒体 Provider 适配器实现；显式导入仅是操作者对来源的声明，不是服务认证。

媒体任务终态费用未知时保留预留。`billing-events` 读取该任务的账单事件；`billing-record` 另需 `task_id`、不可复用的 `event_key`、绝对 `evidence_path` 和 `evidence_sha256`。证据 JSON 使用 `generation-billing-evidence/1`，绑定 task ID、意图哈希、provider、model、币种、实际微单位费用及非空来源引用。首次结算释放预留并登记实际费用，后续修正只记差额，同键重复调用幂等；改写旧证据或同键换内容拒绝。凭证真实性须独立核实，哈希只绑定本地文件。服务端硬封顶违约会阻断 Work 采用，不能被本地账本更正静默放行。

费用以非负有符号 64 位整数微单位保存。`poll` 的终态费用累计若超出 `2**63-1`，返回 `BUDGET_ACCOUNTING_OVERFLOW` 并回滚本次任务状态、事件和预留释放；此前其他任务已成功登记的费用不回滚。后续可查询修正后的有效观察，不重新提交生成任务。本规则防止 SQLite 把溢出整数运算转为浮点数，不自动修复历史损坏账本。

`model-text-deepseek` 是独立的通用文本/function 接口。它支持 `budget-create`、`prepare`、`read`、`result`、`settle-cost` 和显式 `send-once`。`prepare` 通过绝对 `body_path` 与 `body_sha256` 读请求，避免将原文写入 operation request；内容写入权限受限的本地账本，并冻结提供商、端点、模型和请求。模型名由请求体指定，function tool call 只作为未信任数据返回，不执行工具。`send-once` 仅用官方 DeepSeek 端点和 `DEEPSEEK_API_KEY` 发起一次 Chat Completions 请求；调用前账本先记未知提交，之后不自动重试。自定义端点须由上层单独注入显式密钥和 `TextModelRegistry` 客户端，不继承官方环境密钥。`settle-cost` 用账单证据文件哈希、调用身份和幂等事件键进行显式结算或更正；证据真实性由调用方另行核实。其费用预留只有本地记账作用，不构成服务端硬上限，也不属于 W14 图像/视频生成 Provider。发送是付费动作，需单独明确授权和预算；本库未发起任何实网调用。

`model-text` 是配置式文本/function Provider 入口，旧 `model-text-deepseek` 继续可用，但两套账本不自动迁移。默认 `deepseek-default` profile 使用官方 `https://api.deepseek.com`、`deepseek-flash` 与 `DEEPSEEK_API_KEY`；宿主可用 `EDITING_TEXT_PROVIDER_PROFILES_PATH` 指向绝对 JSON 文件，格式为 `{"schema":"model-text-profiles/1","profiles":[{"profile_id":"team-provider","provider_id":"team-provider","endpoint":"https://provider.example/v1","model":"configured-model","credential_env":"EDITING_TEXT_PROVIDER_API_KEY","allow_custom_endpoint":true}]}`。文件只含环境变量名；密钥值由宿主单独配置。自定义 HTTPS 端点必须显式允许，且不得接收 `DEEPSEEK_API_KEY`。profile 的提供商、端点、模型、密钥变量名与许可标记共同绑定哈希。

`model-text/profile-list` 返回公开 profile 与哈希；`budget-create`、`prepare`、`read`、`result`、`send-once`、`settle-cost` 均由 [派发代码](../runtime/model_text_dispatch.py)校验精确字段。`prepare` 必须给出 profile ID/哈希、绝对 `body_path`/SHA-256、预算键与微单位预留；正文包含 `messages` 与 `max_tokens`，可带 function `tools`，模型与端点只能来自冻结 profile。`send-once` 在发出 HTTP 前持久化 `UNKNOWN_SUBMISSION` 和预留，未知结果不自动重试；返回的 function call 只是数据。`settle-cost` 的 `model-text-billing-evidence/1` 文件需绑定 call ID、body/profile 哈希、provider、endpoint、model、currency、实际费用与来源引用。账单证据的 SHA-256 只证明本地文件未变，不证明服务商账单真实性。费用预留不是服务端硬封顶。此接口不生成图片或视频，且未进行真实付费调用。
