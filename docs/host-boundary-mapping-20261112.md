# 显式宿主边界映射与原事务采用

本批把保存 OTIO 分支与**已有批准 BoundaryProposal**相互核对，不新增 Storyboard 权威，也不删除读回原有 CONFLICT。实现入口 `host_boundary_mapping.apply_host_boundary`；仍仅由 `boundary_apply.apply_boundary_proposal → revision.adopt_revision(kind="boundary")` 修改 07/08/09。

## 输入与不变量

调用方提供原包、已封存快照、当前 revision base、已批准且当前摘要一致的 BoundaryProposal、config/timebase 与原证据参数。显式 mapping 包含：

- `schema: film-host-boundary-mapping/1`
- `snapshot_sha256`、`export_package_sha256`、`boundary_proposal_hash`：严格 64 位小写 hex 字符串，不接受 None 或布尔值。
- `instance_ids`：非空字符串、无重复，必须恰覆盖所有实际变化实例，包括自然顺移的后段。
- `track_ends`：每条变化轨的精确 `before/after` 有理数；分子/分母为严格整数（拒布尔值），分子非负、分母正。

宿主变化先用原三方提案重算；只有精确声明的 track-end 映射冲突可继续进入边界准备，其余冲突、当前分支改动、未知依赖及字幕依赖保持拒绝。并非把原冲突状态改成通过。

原边界准备仍核验高光选择、原声/对白、事件/人物/知识揭示、保护、源及批准摘要，并同时更新 07/08/09。准备产物重新投影到原稳定实例 ID，**全部**实例、资源集合及 SHA、源窗/目标窗、轨角色/类型和结束点须与宿主快照相同。没有明确实例 ID 的历史视觉改动仍可能 `LEGACY_VISUAL_IDENTITY_AMBIGUOUS`，不凭位置猜认。

`boundary_apply` 增加可选附加校验钩子：只接收准备产物的深拷贝，返回审计绑定，不能改准备候选。原默认调用不变；锁内重新准备与全部核验。映射内容、摘要及 revision-base 摘要保存到既有 boundary receipt 的 `additional_candidate_binding`，不是 stdout 才有来源。CAS、未知字段/保护检查、原 generation 保留及旧 QC/渲染结果失效仍走原事务。

## 工程验收与真实内容边界

测试媒体为自行生成的彩色视频与正弦音，**所有事件/对白/批准/语义观察均为显式合成测试夹具**，绝不是影视内容金标或替用户作真实剪辑批准。

合成完整工作区初始高光 10–24 秒，已批准合成提案改成 10–22 秒，后续 20 秒合成旁白自然顺移。保存宿主分支先得到三个 track-end CONFLICT；明确对应全部实例/轨变化后，原事务成功 ADOPTED。旧 generation 保留，新 generation 旧 QC 状态失效，映射身份可从原 boundary receipt 追溯。

实际运行正常 `FilmRecapPipeline.render_only()`：pre-QC → FFmpeg render → post-QC → delivery，未 mock QC、未调用付费服务、未绕过门槛。最终两个 QC 都为 **DEGRADED**，不是 PASSED：

- pre：LOW_STORY_CONFIDENCE、SEMANTIC_QC_UNAVAILABLE；语义服务未配置。
- post：VO_CAPTIONS_ESTIMATED、VISUAL_REVIEW_NOT_VERIFIED、AUDIO_REVIEW_NOT_VERIFIED。
- 目标时轴 32 秒；实际容器时长存在编码 padding，按正常 QC 记录，不宣称逐样本无损。未完整看听，未做真实内容效果验收。

受限 Blender ToS 真实桥接工作区仅有 00/09/state，缺 01–08 语义证据和批准 BoundaryProposal；输入检查确认缺少必需依据，**未执行真实采用与采用后 QC**；这不是一次已运行 QC 的返回状态。另一 stage13 工作区虽然有 01–08，但属于低置信度技术登记，亦无批准边界和完整听审；没有把它升级为真实批准证据。本批不制造缺失依据。

## 回归与已修问题

作者新增映射测试与原边界测试合跑，另有独立对抗检查；精确版本的最终数量由整合报告给出。覆盖摘要 None/格式错误、布尔有理数、漏授权顺移/轨尾、错误窗口、未批准/旧版本、输入变更、回调不能篡改候选、锁内重核及失败不改变 revision token。

审查曾实证两个缺陷：`expected_sha=None` 关闭底层绑定，以及 Python `True == 1` 让布尔分母蒙混匹配。现已增加前述严格 schema，旧失败保留，拒绝路径经独立复验；没有把输入验证失败改成警告。

**完成的是受限显式映射的工程事务闭环及合成实际 QC，不是任意宿主工程自动往返，更不是整套产品/真实语义验收完成。** 原字幕、复杂依赖、同时分支修改等不支持情况仍需明确映射设计，不会自动抹掉。
