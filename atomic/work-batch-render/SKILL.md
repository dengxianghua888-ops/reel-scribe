---
name: work-batch-render
description: 按明确作品版本执行本地批量导出、已验证结果复用和有限失败恢复，保留不可变尝试记录；不选创作风格、不自动重剪、不发布或提交收费服务。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# work-batch-render

使用[batch_ops.py](../../runtime/batch_ops.py)，operation=work-batch-render。每次调用的receipt目录是新目录，并且与batch_dir互不包含。

- prepare：绝对batch_dir必须不存在，batch_id，jobs=[{id,store,expected_version,audio_backend?}]。audio_backend 可选且必须为对象；省略时保留 work-render 默认选择。提供时按原值固定到 job，准备只登记选择，不认证该后端可执行；后端具体参数与条件依赖由 work-render 在执行时核验。核对当前工程与依赖，拒绝重复ID或同一store/version，固定文档／运行时／实际FFmpeg与ffprobe字节到manifest.json及SQLite索引。保存返回manifest_sha256。
- status：batch_dir与manifest_sha256。队列的 metadata/jobs/attempts 从同一 SQLite 语句快照读取、校验和返回；释放队列读取后另查 Work 当前版本，两者不是跨数据库原子快照。只查状态和当前版本关系，artifact_integrity=NOT_RECHECKED_STATUS_ONLY，不认证产物当前完整性。
- status/run 对实际解析的同份 manifest 字节核对 manifest_sha256；run 获取 worker 锁后再次核对路径当前身份，观察到变化时在队列写入和渲染前拒绝。不重新解析另一份清单，也不声称持续锁定外部文件或阻止任意同权限进程篡改。
- run：batch_dir、manifest_sha256、job_ids、retry_failed布尔。非阻塞OS锁，BATCH_BUSY时停止当前调用；每个选中任务本次最多一次新render。失败重试需retry_failed=true。成功结果先复核请求、回执、全部产物及输出哈希再复用，不能只看文件存在。显式 audio_backend 必须在实际 work-render 请求、结果绑定与 timeline 子回执一致；实际消费 helper 时重核其路径与字节身份，已变更不能复用。无 DSP 的分支不因未消费的 helper 缺失而失败。当前版本变化拒绝新导出，已有历史成功标RENDERED_HISTORICAL；不回写作品。

每次尝试用新目录jobs/id/attempt-0001，旧失败／中断不删除。拿到锁后，RUNNING有合法最终回执可恢复索引而不重渲染；无回执保留旧尝试并新建一次。恢复到失败回执本次即结束该项，另一次明确retry才执行。控制进程退出不证明FFmpeg已停：实际子进程继承锁fd，仍活着时不能启动第二worker。worker.lock的inode不能替换或清理。

单任务源文件缺失不阻止其他任务，修复源后只重试必要项。环境字节变更要求新batch，不改旧manifest。损坏索引拒绝，保留证据后另建队列；不要手改数据库让状态看起来成功。RENDERED只表示明确版本导出，PARTIAL须列失败项。完整看听、各版本意义、平台规范、宿主打开及发布不由本操作认证。
