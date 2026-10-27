# 长片证据、生成意图与工程恢复的离线合同

本轮从 `207678036cfa24e9b6205ae0f80fe2098bf246bd` 固定源码与既有测试，先去重，再验证 L1–L4、G1–G4、M1–M5 共13组合同。组数不是测试方法数、子例数、真人验收或真实影片质量评分。

## 已证缺口与修改范围

1. **长片漏项不能仅按召回池判断。** 原 benchmark 缺完整分析索引与按 Beat 的规划选择输入，无法定位四层遗漏。现沿用 R0/R1，增加可选观察输入及逐层状态；未测输入保留 UNKNOWN，不从候选存在推定实际采用。
2. **R0 没有执行已配置的 writer 字节上限。** 合法配置12个普通槽位、1100字节上限时，原 R0 实际序列化片段为9239字节。共享已有尾部裁剪规则后，该反例 R0 为993、R1 为622字节，R1不超同一 R0 envelope；默认无显式上限的 R0 选择不变。选中高光独自超预算时两路径均拒绝，不悄悄删高光。这里测量的是实际 JSON `visual_pool` writer片段字节，不是整个提示、provider token、费用或总计算量相等。
3. **同字节重取也必须核本次回执。** 生成账本的 VERIFIED 快路径曾接受 task/provider/job/output/response/checksum 身份错误的新回执并完成新 attempt，尽管原 canonical 链没有改变。共同身份检查先于快路径；验证原链后再次核本次回执及结果SHA，拒绝读取期间发生的已观测变更，任务、attempt、事件保持。这不承诺隔离任意非协作并发。复用原有账本与来源链，不新增生成状态机或缓存。
   原gate把任务固定到原Work版本，不能表达已修订/另一Work的合法固定SHA复用。经独立合同审查后，仅在原 `adoption-gate` 增加显式可选 `reuse`，绑定原结果/receipt/原ACCEPT与当前用途独立评审、目标Work及候选；默认调用不变，无效reuse不降回旧分支。新分支重验全链，只返回CAS资格并幂等追加既有审计，原任务/预算/receipt/评审不改，实际采用仍由既有Work CAS与读回完成。字段和边界见[生成合同](../../contracts/generation-task-contract.md)。
4. **恢复与 OTIO 大部分已有保障。** 补充边界负例和跨入口字节恢复回归，不改变工作区/OTIO格式、安全与冲突语义或 `render_cache` 的 COMPLETE 原子发布。
5. **包清单漏掉了现有模块。** 固定基线包在源码目录外以 `python -I` 导入 retrieval/OTIO readback 均报模块不存在。显式补齐13个既有film模块及本轮文档/直接引用测试；其中retrieval的修改见前述，其余12个模块实现字节与基线一致。新增包迁移后的隔离导入回归，断言模块全部来自包目录。没有改格式、检查器或自动包含任意磁盘文件。

## 13组合同映射

| 组 | 核验对象 | 本轮证据与边界 |
|---|---|---|
| L1 | 尾部合取证据 | 120分钟、240单元的元数据fixture含前段诱饵、后半动作A与下一镜反应B；gold只有AB合取。冻结观察摘要与各层指标；合成planned/consumed轨迹仅核诊断，真实writer/消费未运行，R0缺轨迹保持UNKNOWN |
| L2 | 时间分散反例 | 首中尾候选均为高词分，尾C也进入实际R1池；C并不支持Beat。只选三个时间点或仅C仍不满足AB；时间多样性不是语义oracle |
| L3 | 同预算/知识限制 | 同index、Beat、highlight及ordinary上限，核长摘要writer预算、重复ID拒绝/不扩容量、未来knowledge/foreignsource排除和未覆盖UNKNOWN；不冒称同token |
| L4 | 四层故障注入 | 分析索引、writer池、规划、消费各移除B并正确定位；未知上游不伪归因后层。缺消费UNKNOWN，旧global消费不认证单Beat，空gold NOT_RUN |
| G1 | 恢复同任务 | SQLite重开、同key及原job/output、失败传输后重取，submit总计1；丢ACK、UNKNOWN/NOT_FOUND及无查询能力均不自动换key重发；同key换意图拒绝 |
| G2 | 指定已验收SHA复用 | 显式reuse pin原来源/ACCEPT并提供当前用途独立proof，新增submit0、真实隔离Work SQLite CAS/readback；相同绑定重复或同SHA locator迁移audit仍1，旧review不能代签新用途，任何来源/target/candidate/proof漂移拒绝 |
| G3 | 同提示词重新创作 | 固定seed与无seed两组均明确使用新task/key/job/output及新回执/评审，每新task一次submit；结果字节和候选JSON可以相同，fake不证明服务真实确定性 |
| G4 | 结果/Work漂移 | 来源结果、receipt、candidate/review变化分别拒绝，当前Work基线变化保留原CAS冲突；原指针与后来修改不覆盖。UNKNOWN恢复归G1，有/无查询能力均不自动换key |
| M1 | 同名不同字节 | 两个外部派生产物同basename但不同SHA分别保留；归档同名成员同长度换字节也以RECOVERY_MEMBER_MISMATCH拒绝、目标不创建；OTIO同resource ID换字节保持身份冲突，不按文件名混用 |
| M2 | 同SHA迁移 | 既有安全相对OTIO迁移与固定B恢复CLI核SHA；恢复仅RECOVERED_BYTES_ONLY、production_authorized=false，不自动relink原媒体或继承QC |
| M3 | 缺媒体/旧绝对路径 | 缺归档成员恢复拒绝且目标不创建；OTIO缺文件、存在的旧绝对路径/file URL也不猜relink，raw保存、资源不复制、CONFLICT、无采用或宿主写入 |
| M4 | 越界/软链 | 内部软链、同SHA恢复成员软链也拒绝；失败不创建恢复目标，不放宽原安全语义 |
| M5 | 并发/未知效果 | 后来手改保留、指针不切换；未知宿主效果与不可读live origin保留冲突/UNKNOWN，不把历史保存分支当已应用 |

方案L1–L4案例不等于四个诊断layer的编号。[方案用例](../../workflows/raven-film-recap/douyin-film-recap/tests/test_retrieval_plan_cases.py)与[冻结输入/gold](../../workflows/raven-film-recap/douyin-film-recap/tests/fixtures/retrieval-plan-v0.json)补齐首中尾C反例及重复候选检查。其余持久回归分别位于：[四层诊断](../../workflows/raven-film-recap/douyin-film-recap/tests/test_retrieval_layers.py)、[G组](../../tests/runtime/test_generation_intents.py)、[OTIO读回](../../workflows/raven-film-recap/douyin-film-recap/tests/test_otio_readback.py)、[M1/M2固定B恢复](../../workflows/raven-film-recap/douyin-film-recap/tests/test_recovery_relocation_contract.py)。已有工作区迁移负例见[迁移测试](../../workflows/raven-film-recap/douyin-film-recap/tests/test_workspace_migration.py)。其余一次性固定B跨入口检查与持续CI用例在交付报告中分别计数，不将前者冒充已在CI执行。

在 film 子包中可用 stdlib unittest 运行 L组与既有 retrieval/config、OTIO读回；G组从仓库根执行：

```sh
PYTHONPATH=tests/runtime python -m unittest test_generation_intents test_generation_budget_overflow -v
```

上述测试需源码checkout和相应开发依赖；随包只保留本页直接引用的部分回归，不声明包含完整开发测试树。film子包的 `tests/test_package_import_closure.py` 另外验证两包迁移后的独立导入，需该子包已有的正式依赖，不能放在仅安装通用runtime依赖的测试环境。全量 pytest、官方 OTIO 0.18.1 parser与静态检查以 PR 的精确提交 CI 结果为准，不用基线绿灯代签。结构、portable/plugin构建和隔离导入只证明包和链接/模块合同，不证明安装、真实编辑器或成片效果。

## 仍未认证的内容

四层诊断比较调用方提供的 ID 观察，不独立观看/理解原片，也不证明消费了完整源区间、动作或情绪。合成gold通过不是实际长片召回率提高。`adoption_gate`仍只核调用者传入的Work token并返回 `READY_FOR_WORK_VERSION_CAS_ONLY`，显式reuse也不读取或修改WorkStore；实际当前Work须独立读取、当前用途评审、CAS和采用后读回。隔离SQLite测试中的媒体元数据由SyntheticMediaTools明确声明，验证工程结构/范围/CAS，不认证真实媒体时钟或质量。

本轮不重新生成用户媒体、不调用付费provider；真实影片/模型质量、真实provider、具体NLE版本往返、实际宿主CAS和完整视听验收均NOT_RUN。已有两旧母版的用户人工听检记录及历史机器FAIL、严格AAC采样FAIL保持各自版本和范围，新无声插画不能由此升级为有声成品PASS。没有重造缓存、接入新格式或替代原QC。

## 机制参考与许可

- [Crayotter时间多样性实现](https://github.com/idwts/Crayotter/blob/8b7478f22e76311b485ca59ed061ad016deb936e/script/tools/recall_semantic_segments.py)与[长片反例](https://github.com/idwts/Crayotter/blob/8b7478f22e76311b485ca59ed061ad016deb936e/tests/test_long_video_coverage.py)用于设计时间覆盖不等于语义支持的负例；其[论文](https://arxiv.org/abs/2606.07636)解释阶段工件的可追踪目标。[许可证](https://github.com/idwts/Crayotter/blob/main/LICENSE)为 PolyForm Noncommercial 1.0.0，不能按通常开源许可处理。本轮只参考机制，不复制实现/提示/skill或采用可绕充分性的策略。
- [OpenMontage缓存资格](https://github.com/calesthio/OpenMontage/blob/e01dbf433f46eeb91d39bf905e194162921019a3/tools/base_tool.py)及[伪工具测试](https://github.com/calesthio/OpenMontage/blob/e01dbf433f46eeb91d39bf905e194162921019a3/tests/tools/test_base_tool_cache.py)区分deterministic/seeded/stochastic资格；这些是其策略，固定seed和fake测试不证明真实服务字节确定性。本库不引入其代码/依赖、不替换原子缓存；[许可证](https://github.com/calesthio/OpenMontage/blob/main/LICENSE)为AGPLv3。
- [OTIO file-bundle说明](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/94e1ad6c9b3c550b7ef06d999166c99b4be3025a/docs/tutorials/otio-filebundles.md)的同名资源与缺媒体策略，以及[序列化测试](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/main/tests/test_serializable_object.py)，只用于对照身份、缺项和读写读的测试模式；不新增OTIOZ/D格式，不放宽本库安全子集。[许可证](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/main/LICENSE.txt)为Apache-2.0。未复制测试代码；main快照不等于既有CI parser pin0.18.1，也不代表具体NLE往返通过。

上述公开来源于本轮核对许可与机制；仓库及源素材既有独立许可范围未改变。无新依赖或统一许可授予。
