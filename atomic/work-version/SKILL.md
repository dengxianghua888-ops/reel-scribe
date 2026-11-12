---
name: work-version
description: 在明确本地作品库中初始化、读取、提交候选、登记明确内容保护或恢复指定历史版本，并对已核验严格媒体候选执行当前交付选择、读取、恢复或清除；使用版本令牌与事件号拒绝旧写入，不判断内容或替代真人验收。
---

# 同一作品的版本与恢复

本 Skill 要求同一作品的当前修订、历史、受限写入和恢复语义；可由当前编辑器的项目版本/API、Agent 已有同作记录或下述本地 Work 实现。按[通用能力交接](../../contracts/capability-handoff.md)核实际工具的读写与读回能力，不要求编辑器工程先导出 SQLite。缺修订标识、冲突拒绝或恢复能力时，准确报告该项缺口。

## 本库本地 Work 实现

执行 [作品合同](../../contracts/work-contract.md) 的 work-version，action 为 init/read/commit/set-protection/restore/relink-style-resources/prepare-local-undo。作品目录中的 SQLite 是权威状态，每次调用的 work-state.json 是只读快照；不要修改数据库或把旧导出文件当最新状态。

先 read，再基于返回 version/document 生成候选。commit 同时校验最新令牌、候选基础、修改范围与源文件；即使候选文件重算了哈希，也不能绕过范围。用户的最新手工修改需通过当前可用适配器登记成版本，不能假称这里自动监听了外部编辑器。

旧样式卡只发生存放路径变化时，可用 `relink-style-resources`：从当前 head 的 card 精确给 from，新普通文件 to 必须同 SHA、不同规范绝对路径；只追加 path 维护，不改历史或作品 ID，不重验媒体/保护。旧卡语义不能通过改 expected SHA 升级。旧 candidate/交付选择因新令牌失效，先重读再续作。

restore 可选 `style_resource_relocations` 只重定位目标历史中的同 SHA 样式卡，仍执行完整媒体与保护校验；失败不得降级成维护成功。

restore 会以指定历史内容追加新版本，保留中间历史；恢复后的令牌不同于旧令牌，旧候选不会重新有效。只要用户明确要求恢复就执行，不额外索要常规确认；全片恢复与局部恢复范围必须区分。

内容保护属于作品版本。普通 commit 不可增删或改写保护声明；明确登记/修订保护时使用 set-protection，传 protection、change_basis、expected_version、message、author；protection:null 为显式撤销。原子仅记录依据，不判断用户是否授权，不能把 author=human 当批准证明。完整 restore 连同保护一起恢复，可能回到无保护的历史版；按用户指定的恢复范围调用，不能借恢复绕过普通修改限制。

WORK_BUSY 表示其他写事务占用，先重读或核对句柄；WORK_VERSION_CONFLICT 必须重新读取并重新判断，不以修改 expected_version 强行覆盖。若数据库提交后导出失败，先 read 检查是否已提交，避免重放。

## 宿主工程桥

`host-bridge` 的 export/import/prepare-patch/rebase-patch/preview-patch/prepare-import 将当前 Work 版本与宿主中立快照相互映射。先用 `work-version read` 取得当前状态；宿主手工修改经 `prepare-import` 生成候选，再以 `timeline-revise` 校验范围，人工检查后用当前令牌执行 `work-version commit`。Work 到宿主的补丁只在目标字段旧哈希与宿主 revision 均匹配时可写；`preview-patch` 只是内存预览，不能当作宿主工程已保存。原生未知字段保留在旁路，并报告无法完整往返。具体字段、CAS 和未选定宿主的限制见 [宿主桥合同](../../contracts/host-bridge-contract.md)。

选择本地 Work 时，数据只在指定本地库，非多人服务、非 NLE 自动同步。真实执行与限制见 [实现](../../runtime/work_ops.py)。

## 当前交付指针

当用户明确要在同一作品中选用一份已经核验的严格媒体母版时，先读作品当前头和 `work-delivery read` 的最近事件，再以 `work-delivery select` 传当前版本、事件号、成功回执、Work 交付绑定和决策记录。`restore` 选择历史有效事件，`clear` 回到普通 `work-render`；四个动作由 [交付实现](../../runtime/delivery_ops.py)执行。事件只改变交付指针，不修改 Work 文档、片段或历史修订。原子不自行决定是否采用候选。

读取会重新核作品头、媒体、严格 helper、请求与 FFmpeg/ffprobe 工具链。任一身份失效则返回 `RENDER_FALLBACK`；不能把旧回执改名后选择。此操作始终标记 `publishable=false`，完整视听、播放器兼容和真人手改验收另行完成。

## 保留后续手改的受限局部撤销

`prepare-local-undo` 只准备标准候选，不提交。输入当前 `expected_version`、历史普通提交 `undo_sequence`、精确结构化 `fields` 和现有完整 `scope`。支持 `{kind:caption_style,field:font_size|margin_v|color_rgb}` 及 `{kind:audio_track,id:既存轨ID,field:gain_db}`。比较历史前值/后值/当前值：当前仍为后值才恢复前值，已为前值返回 NO_OP（无候选），第三值冲突拒绝。保留全部未选择的后续修改；历史缺字段、删轨或音轨源/窗口/锚点身份改变均拒绝。

有现存样式绑定且需要变化时，本入口不支持局部 undo，须使用既有显式 recipe/范围路径处理并重验；不得建议清除绑定或约束绕过。不会静默改绑定、字体、源、时序或内容保护。检查候选后另行使用现有 commit，旧头仍拒绝。结果不代表渲染、听审或真人编辑器验收。
