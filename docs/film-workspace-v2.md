# 影视工作区 Schema 2：迁移、发送与只读恢复

本页对应本地候选的工作区协议 `film-workspace/2`、完整身份 `sha256-full/2` 和发送意图 `film-send-intent/1`。版本名不代替源码与发行包 SHA。影视运行依赖 Python 3.11+；当前协作锁使用 `fcntl`，支持范围是 macOS/Linux，尚未验收 Windows。

## 新项目与旧项目

新项目直接创建 Schema 2。源文件、字幕侧车和允许使用的上下文采用完整流式 SHA；修改来源或配置会先保全旧工作区字节，再创建 `.generations/<intent>`。活动指针为 `.film-workspace.json`，旧 JSON 和旧产物保留原位。源媒体不自动复制进归档。

Schema 1 默认拒绝生产运行。先构建并独立验证只读维护候选 B，再固定 `recovery-package.json` 的 SHA：

```sh
python scripts/build_film_recovery_bundle.py --out /new/path/recovery-B
python /new/path/recovery-B/recover.py inspect --work-dir /existing/task
```

构建输出 `BUILT_BYTES_VERIFIED` 只证明复制字节与清单一致；B 必须通过 inspect 的 1/2/未知版本矩阵、所有生产入口拒绝及真实 recover CLI 测试，才可作为当前候选的恢复资格证据。当前源码预检同时核调用者固定的包 SHA、成员闭包、启动入口和本候选恢复源码，不能用任意自声明维护包代替。

迁移示例（`B_MANIFEST_SHA` 使用已核验候选的实际值）：

```sh
douyin-film-recap run /authorized/source.mp4 --work-dir /existing/task \
  --config config.yaml --until ingest --migrate-legacy \
  --recovery-bundle /new/path/recovery-B --recovery-bundle-sha256 B_MANIFEST_SHA
```

迁移清单分别保存旧回执期望 SHA 和迁移观察到的实际 SHA。人工编辑与旧回执不一致时仍保全当前字节。清单覆盖 state、阶段 JSON、阶段快照、人类脚本、生成音频及请求缓存、交付目录、评审材料，以及回执/JSON 明确引用的外部派生产物。外部派生产物存入 `external/<path-digest>/`，不会改写原路径。原媒体、原侧车等只登记引用与完整身份。未被回执引用的调试目录可以不归档，不声明归档涵盖所有私人目录或完整历史；缺少必须引用的成员则阻断迁移。

迁移与普通状态写入持同一任务锁。复制后核 SHA、成员集合、原活动成员、指针、新代际 state/marker，并在最后切换前再次比较。容量不足、复制失败、成员/指针/候选漂移均不接纳新代际。中断暂存目录保留为未完成尝试；归档/候选完成后重入复用同一意图；切换后的重入补齐状态，不再次失效。锁协调合作进程，不能约束不认识该协议的旧程序或同权限恶意进程。原子写入不等于断电耐久性已经验收。

## 远程调用

API Key 只是凭据。CLI、直接 `Pipeline.run()` 和实际模型/TTS 发送入口都使用同一发送会话。缺少授权时可以执行本地阶段、复用已保存回复；新发请求被拒绝。Agent 应将用户已有的有效授权转换为本次范围参数，不需要再向用户索要同一授权。

```sh
douyin-film-recap run /authorized/source.mp4 --work-dir /task --config config.yaml \
  --until storyboard --allow-remote --max-remote-requests 12
```

授权保存于 `.remote-authorization.json`，绑定来源、配置、实际 endpoint、模型、TTS 参数和选定阶段。相同绑定且阶段范围不扩大时可复用有效授权。新发送在本地能力准备后和调用 transport 前再次核对已绑定授权；授权文件缺失、损坏或已变化则拒绝。准备阶段发现撤回时不预留发送，预留后但尚未进入 transport 时发现撤回则记 `NOT_SUBMITTED_CONFIRMED`，已有预留仍保守计入次数。已保存成功回复的只读重放仍不需要新授权。检查只覆盖可观察的调用边界，不是连续文件锁或服务端撤销保证。请求上限跨线程、阶段与重入保留计数，达到上限则停止；新 `--allow-remote` 是显式重新授权。这个计数是本地发送次数约束，不是服务端计费封顶。

`.receipts/recompute-plan.json` 是本次范围记录；`.remote-intents` 保存提交记录与原始回复。意图由阶段、分段/批次及调用角色确定，请求体 SHA 独立保存；JSON 修复、格式回退、拟合前后 TTS 各有独立角色。跳过前段缓存不会改变后段意图。成功回复先写入记录，再解析 JSON 或做内容校验。回复可核 SHA 后重放，不能将一个无效回复当作有效模型结果。

发送前先持久化 UNKNOWN。超时、断连、进程终止均不能证明服务未接收，运行时不自动重发。只有明确收到格式不支持的 HTTP 回复，才可按另一个受控意图进行格式回退。遇到 UNKNOWN，应先核对实际服务；若已确认未提交，可以记录人工证据：

```sh
douyin-film-recap reconcile-send /task --intent INTENT_SHA \
  --confirmed-not-submitted '实际服务核对证据与责任人'
```

这条命令记录操作者断言，运行时不替服务认证它。之后发送仍受有效授权和剩余次数约束。保存的回复、UNKNOWN 和人工核对记录不能随重算清除。不得将本地回执解释为服务端 exactly-once 保证。

## 只读恢复与版本矩阵

```sh
python /fixed/recovery-B/recover.py recover --archive /task/.migrations/INTENT \
  --out /entirely/new/recovered-task
```

恢复先核清单与成员，目标必须全新且在原任务/归档之外；拒绝链接、缺失、重复、漂移成员与已有目标。清单从实际解析的同一份字节绑定 SHA，恢复前固定该身份，复制后及回执前复核同一清单和目标字节、成员集合；即使替换后的归档自身校验一致，也不能为旧清单恢复出的成员出具新清单回执。可观察的清单变化返回 `RECOVERY_MANIFEST_DRIFTED`，已复制的部分目标保留以供检查，不自动删除或报告成功。回执仅写 stdout，避免覆盖同名恢复成员。状态为 `RECOVERED_BYTES_ONLY`，不重新认证来源、passed 阶段、QC、创作质量或继续生产权限。

同名的外部派生产物仍按各自完整原路径的摘要进入不同 `external/<path-digest>/` 成员，不能因文件名相同混用字节。恢复到新目录保持成员 SHA，也保持旧 JSON 中的原绝对引用；它不是自动重连。源媒体引用不随恢复重新认证，旧 Schema 的 passed 值只是被保全的历史字节，新生产代际仍须按当前身份重算。安全的同 SHA 媒体迁移与错误字节、缺媒体、旧绝对路径、软链和并发冲突的读回边界，另见[OTIO 保存分支合同](../workflows/raven-film-recap/douyin-film-recap/docs/otio-readback.md#offline-media-relocation-checks)；该合同也不执行 NLE 写入或自动采用。

| 入口 | v1 | v2 | 未知 Schema |
|---|---|---|---|
| 固定 B | inspect、向全新目标 recover | inspect、按恢复清单 recover | 写入前拒绝 |
| 当前 V2 | 显式迁移 + 固定 B，再从 ingest 重算 | 按当前绑定运行 | Pipeline/Provider/状态写入前拒绝 |
| 原始 U | 不支持作为回滚版本 | 不保证识别新状态、锁或指针 | 不保证拒绝 |

B 的 run/resume/render/tts/delivery 始终拒绝。恢复出的旧文件不能在旧 U 中继续生产；需要当前 V2 显式迁移、完整来源核验、授权与独立 QC。

## 验证与保留限制

源码回归覆盖手改字节、四处中断、重复迁移、竞争/成员漂移、固定 B 的实际 CLI、普通/直接运行发送门禁、模拟 Provider/TTS、线程池和未知提交恢复。合成 FFmpeg 用例覆盖安全新 attempt、中文 ID、来源替换和快照消费。不能由这些测试推导真实 Provider 行为、实际客户端安装、正版长片内容质量或人工时间线往返已经通过。

通用编辑运行时可显式选择 `source_consumption` 的 `boundary` 或 `snapshot`，见 [操作合同](../contracts/operation-contract.md)。boundary 的消费前后摘要无法发现完整 A→B→A 瞬时替换；snapshot 使用独立副本并核原/副本完整身份，不抵抗同权限恶意进程。当前固定 Rubber Band helper 尚缺真实 DSP 验证；atempo 用例不能代签。当前 FFmpeg 6.1.1 上还观察到纯静音经 loudnorm/AAC 的 NaN 失败，该输入不在本轮可用性通过范围内。
