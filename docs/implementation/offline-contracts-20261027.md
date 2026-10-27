# 长片证据、生成意图与工程恢复的离线合同

本轮从 `207678036cfa24e9b6205ae0f80fe2098bf246bd` 固定源码与既有测试，先去重，再验证 L1–L4、G1–G4、M1–M5 共13组合同。组数不是测试方法数、子例数、真人验收或真实影片质量评分。

## 已证缺口与修改范围

1. **长片漏项不能仅按召回池判断。** 原 benchmark 缺完整分析索引与按 Beat 的规划选择输入，无法定位四层遗漏。现沿用 R0/R1，增加可选观察输入及逐层状态；未测输入保留 UNKNOWN，不从候选存在推定实际采用。
2. **R0 没有执行已配置的 writer 字节上限。** 合法配置12个普通槽位、1100字节上限时，原 R0 实际序列化片段为9239字节。共享已有尾部裁剪规则后，该反例 R0 为993、R1 为622字节，R1不超同一 R0 envelope；默认无显式上限的 R0 选择不变。选中高光独自超预算时两路径均拒绝，不悄悄删高光。这里测量的是实际 JSON `visual_pool` writer片段字节，不是整个提示、provider token、费用或总计算量相等。
3. **同字节重取也必须核本次回执。** 生成账本的 VERIFIED 快路径曾接受 task/provider/job/output/response/checksum 身份错误的新回执并完成新 attempt，尽管原 canonical 链没有改变。共同身份检查先于快路径；验证原链后再次核本次回执及结果SHA，拒绝读取期间发生的已观测变更，任务、attempt、事件保持。这不承诺隔离任意非协作并发。复用原有账本与来源链，不新增生成状态机或缓存。
4. **恢复与 OTIO 大部分已有保障。** 补充边界负例和跨入口字节恢复回归，不改变工作区/OTIO格式、安全与冲突语义或 `render_cache` 的 COMPLETE 原子发布。
5. **包清单漏掉了现有模块。** 固定基线包在源码目录外以 `python -I` 导入 retrieval/OTIO readback 均报模块不存在。显式补齐13个既有film模块及本轮文档/直接引用测试；其中retrieval的修改见前述，其余12个模块实现字节与基线一致。新增包迁移后的隔离导入回归，断言模块全部来自包目录。没有改格式、检查器或自动包含任意磁盘文件。

## 13组合同映射

| 组 | 核验对象 | 本轮证据与边界 |
|---|---|---|
| L1 | 分析索引遗漏 | 120分钟、240单元的元数据fixture含前段诱饵、后半动作与下一镜反应；gold中动作和反应必须同时存在。索引缺反应定位L1；诱饵不是gold |
| L2 | 检索/预算遗漏 | 分开完整排序候选与实际writer池；同实际字节envelope，明确知识过滤与writer预算差别；索引未知时不伪归因 |
| L3 | 规划未选 | writer池完整不等于planner已选；按Beat提供规划ID，另一Beat不能代签 |
| L4 | 实际消费未用 | 按Beat消费ID与规划分开；缺消费UNKNOWN，旧global集合只保留旧全局指标，不能认证单Beat；空gold仍NOT_RUN |
| G1 | 恢复同任务 | SQLite重开、同key及原job/output、失败传输后重取，submit总计1；同key换意图拒绝 |
| G2 | 指定已验收SHA复用 | 保留原生成来源与canonical回执；错身份、变字节拒绝，旧Work gate不代签另一个Work |
| G3 | 同提示词重新创作 | 明确新意图使用不同task/key/job/output及新回执/评审，submit为2；结果字节和候选JSON可以相同 |
| G4 | UNKNOWN不重发 | 丢ACK、UNKNOWN/NOT_FOUND、有/无查询能力均保留原key/预留，不自动换key；不以payload相同擅自推断用户意图 |
| M1 | 同名不同字节 | 两个外部派生产物同basename但不同SHA，归档与恢复分别保留；不能按文件名混用 |
| M2 | 同SHA迁移 | 既有安全相对OTIO迁移与固定B恢复CLI核SHA；恢复仅RECOVERED_BYTES_ONLY、production_authorized=false，不自动relink原媒体或继承QC |
| M3 | 缺媒体/旧绝对路径 | 即使旧绝对路径存在也不猜relink；raw保存、资源不复制、CONFLICT、无采用或宿主写入 |
| M4 | 越界/软链 | 内部软链、同SHA恢复成员软链也拒绝；失败不创建恢复目标，不放宽原安全语义 |
| M5 | 并发/未知效果 | 后来手改保留、指针不切换；未知宿主效果与不可读live origin保留冲突/UNKNOWN，不把历史保存分支当已应用 |

持久回归分别位于：[L组](../../workflows/raven-film-recap/douyin-film-recap/tests/test_retrieval_layers.py)、[G组](../../tests/runtime/test_generation_intents.py)、[OTIO读回](../../workflows/raven-film-recap/douyin-film-recap/tests/test_otio_readback.py)、[M1/M2固定B恢复](../../workflows/raven-film-recap/douyin-film-recap/tests/test_recovery_relocation_contract.py)。已有工作区迁移负例见[迁移测试](../../workflows/raven-film-recap/douyin-film-recap/tests/test_workspace_migration.py)。其余一次性固定B跨入口检查与持续CI用例在交付报告中分别计数，不将前者冒充已在CI执行。

在 film 子包中可用 stdlib unittest 运行 L组与既有 retrieval/config、OTIO读回；G组从仓库根执行：

```sh
PYTHONPATH=tests/runtime python -m unittest test_generation_intents test_generation_budget_overflow -v
```

上述测试需源码checkout和相应开发依赖；随包只保留本页直接引用的部分回归，不声明包含完整开发测试树。film子包的 `tests/test_package_import_closure.py` 另外验证两包迁移后的独立导入，需该子包已有的正式依赖，不能放在仅安装通用runtime依赖的测试环境。全量 pytest、官方 OTIO 0.18.1 parser与静态检查以 PR 的精确提交 CI 结果为准，不用基线绿灯代签。结构、portable/plugin构建和隔离导入只证明包和链接/模块合同，不证明安装、真实编辑器或成片效果。

## 仍未认证的内容

四层诊断比较调用方提供的 ID 观察，不独立观看/理解原片，也不证明消费了完整源区间、动作或情绪。合成gold通过不是实际长片召回率提高。`adoption_gate`只核调用者传入的Work token并返回 `READY_FOR_WORK_VERSION_CAS_ONLY`，实际当前Work仍须独立读取、内容评审、CAS和采用后读回。

本轮不重新生成用户媒体、不调用付费provider；真实影片/模型质量、真实provider、具体NLE版本往返、实际宿主CAS和完整视听验收均NOT_RUN。已有两旧母版的用户人工听检记录及历史机器FAIL、严格AAC采样FAIL保持各自版本和范围，新无声插画不能由此升级为有声成品PASS。没有重造缓存、接入新格式或替代原QC。

## 机制参考与许可

- [Crayotter论文](https://arxiv.org/abs/2606.07636)及[项目说明](https://github.com/idwts/Crayotter/blob/main/README_CN.md)用于理解阶段工件、可追踪观察与历史经验的边界；[许可证](https://github.com/idwts/Crayotter/blob/main/LICENSE)为 PolyForm Noncommercial 1.0.0。本轮只参考机制，没有复制代码、提示词或技能文件。
- [OpenMontage说明](https://github.com/calesthio/OpenMontage/blob/main/README.md)的checkpoint与决策记录用于对照已有恢复机制；[许可证](https://github.com/calesthio/OpenMontage/blob/main/LICENSE)为AGPLv3。未引入其实现或依赖，也不继承其效果/预算保证。
- [OTIO官方序列化测试](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/main/tests/test_serializable_object.py)只借鉴读写读、身份与等价性分层的测试模式；[许可证](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/main/LICENSE.txt)为Apache-2.0。未复制测试代码；官方parser通过也不代表具体NLE往返通过。

上述公开来源于本轮核对许可与机制；仓库及源素材既有独立许可范围未改变。无新依赖或统一许可授予。
