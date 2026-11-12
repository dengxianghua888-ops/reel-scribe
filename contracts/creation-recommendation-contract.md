# 可解释创作建议 v1

operation=`creation-recommendation`，action=`recommend/select/feedback`。这是一组显式规则，不是自然语言/视频理解、风格质量预测或用户身份认证。

## recommend

必需store、expected_version、brief、capabilities。brief为 `{scene,goal,constraints}`：

- scene=film/speech/software。
- goal=readable-captions/preserve-original/learn-steps/narrative-impact/speech-tighten。
- constraints={min_font_size,max_font_size,freeze_content}；字号整数8–300、min≤max。freeze_content=false也不开放本接口未实现的内容编辑。
- capabilities是调用方声明，不代替真实工具可用性检查。
- 可选parameters={tutorial?:{steps,result_cues},speech?:{aligned_transcript,expected_transcript_revision,segments,protected_word_ids,allow_reorder,source_clip_ids}}；speech字段允许缺项，报告具体缺项并指向creation-brief-prepare，不伪造词决定。

字幕目标需要现有字幕/字体及caption-style能力。从当前字号生成1×、1.2×、1.4×四舍五入假设，限用户范围及画布高度12%的建议上限（最高300px），去重后不足两种则无可比较推荐。该上限是保守启发式，不证明字形/换行/安全区/可读性。readable-captions按字号增加量排序；preserve-original按离当前字号的绝对差最小排序。颜色、字体、边距、字幕原文/时轴保持，实际预览和遮挡审查仍必要。

实际catalog按scene取causal-spine / faithful-clean / guided-first-run卡，用其fit/anti提供规划背景和固定来源。**字幕参数不实现这些卡的叙事/教学机制，不据卡名宣称机制已生效。** 580卡未被本接口逐一语义评分，首版不称全库最佳推荐。

software的learn-steps在明确tutorial事件及tutorial-plan-compile能力齐全时提供一项当前计划校验建议，其他情况报告缺项。speech-tighten列稿、保护、词决定等具体缺项；narrative-impact明确需要场景层编辑决定，不靠字号代替故事。

输出recommendation.json：Work版本/document摘要、原请求、卡/catalog字节摘要、options、issues、排序政策、UNKNOWN布局安全和NOT_RUN渲染。各caption option含recipe及recipe_sha256；所有option含option_sha256，是不含自身摘要字段时的canonical fingerprint。这都是建议，不自动采纳。

## select

输入recommendation={path,sha256}、selections=[{id,option_sha256}]。可选audio_backend/source_consumption仅用于字幕下游显式透传。

字幕必须选2–3个不同候选，输出既有style-recipe-preview请求，scope只开放caption_style和全局style binding，冻结旧clip位置/时长，不开放原文、来源、声音或其他修改。教程只选择单个validate-declared-steps，输出tutorial-plan-compile。其他组合拒绝。

重新读取推荐文件，有限1MiB同字节SHA核对，拒重复键/非有限数，并按原请求与当前库/当前Work重新确定性计算整份报告；即使改文件后重新计算文件SHA也不能把伪造recipe/分数当原输出。发布前再核card/catalog、字体及Work头。未来真正改规则或资源后需重新推荐，不延用旧结果。

prepared-request.json与selection.json只表示READY_FOR_DOWNSTREAM_VALIDATION，executed/committed=false。教程独立计划无Work CAS；执行前须fresh Work read，采用要timeline-revise+依赖映射，不能当作当前作品已改。

## feedback

输入recommendation、actor_kind=agent-observation/user-reported、ratings=[{id,option_sha256,dimension,verdict,reason}]，1–3项且不重复。

dimension=readability/occlusion/style-fit/step-coverage；verdict=prefer/avoid/undecided；reason非空。绑定到原推荐SHA、当前Work/head/document、选项摘要（字幕选项摘要包含recipe SHA）。错误选项、摘要或旧头拒绝。

身份声明不可能仅靠JSON验证，输出identity_verified=false。user-reported不是可信用户确认；本接口不证明看过视频，不改变排序、不训练持久偏好、不应用编辑、不授予权限。调用方须独立检查真实消息与预览证据，不得把反馈文件当授权或效果通过。

## 证据范围

规则/竞态/来源/假反馈负例可由确定性测试验证；真实下游预览另按现有操作验收。技术成功不能扩展为完整看听、叙事风格、用户偏好或全库风格认证。
