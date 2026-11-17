# 已绑定渲染记录的支持窗口诊断（第十三切片）

目标是发现“证据ID选过，但声明的关键范围没有在本Beat的渲染记录中完整出现”。这不是新召回策略、自动故事判断或发布门槛。默认R0、旧ID指标、pre/postQC与09 Storyboard唯一执行依据保持不变。

## 已实现范围

既有影视`revision-preview`可选`--support-windows FILE`，支持同Beat的合取窗口和备选支持组；不传时旧行为保持。复用原渲染状态、产物身份、EDL/Storyboard、源及render-plan验证，不接受游离EDL或未渲染候选补造消费。CLI可选文件用同一次bytes计算摘要并解析，输出前重查。

仅original单源连续1×、毫秒可精确表达的起点/时长，以及源/segment契约/实际测得帧时长/realized timeline均吻合时，求精确有理数区间并集与缺口。重复段不重复计量，另一Beat即使相同源同窗也不能补本Beat。映射不足、旧非增量渲染无绑定记录、候选未渲染等保持UNKNOWN。

状态为RECORDED_WINDOW_FULL/PARTIAL/MISSING或UNKNOWN，HTML逐项显示缺口与未知原因、声明依据并转义所有动态文本。FULL明确只是**记录窗口覆盖**。源seek后的实际首末帧PTS/逐帧映射未记录，输出帧数不能补造这些证据；physical_frame_coverage=NOT_VERIFIED、media_reverified=false、semantic_review=NOT_RUN始终保留。声明支持窗不是语义金标，也不自动登记内容保护或继承QC。

## 定向检查

作者23覆盖测试+50已有预览测试+29报告测试共102通过。独立15个对抗探针通过：伪渲染状态、错误source/contract、少1帧、跨Beat误计、VO映射缺口、缺EDL及HTML注入。它们主要为合成记录，不能冒充真实渲染或语义验收。确切最终提交全量回归和CI另行绑定，不用此前阶段结果替代。

## 真实许可素材执行与边界

复用 Blender Foundation [Tears of Steel](https://mango.blender.org/sharing/) CC BY3.0 既有原片（SHA `efa9062d9cdb7a338e40ad530dfdf234806743f29ae6a1a136b97ece4e588e8f`），不下载新影片或使用独立BY-ND音轨。通过隔离字节副本与唯一英文SRT解决原目录中英sidecar歧义；SRT为官方标注，未独立听译。

初拟整数切点截入字幕边界而未执行，未放宽QC。新25–42秒单original段、24fps、1×共17秒；首次未选hook被正常preQC阻断并只读返回UNKNOWN，保留证据。后来明确选该真实段为技术开场候选，不冒称审美高光、人物/故事已验证；默认非增量渲染正常完成但无绑定render_plan，预览仍按旧契约UNKNOWN。最后新隔离运行显式启用已有incremental_cache，未改默认行为或门槛，正常preQC→render→postQC→delivery完成，产物与状态来自真实管线，不手填passed。

最终preQC **DEGRADED**：LOW_STORY_CONFIDENCE、ORIGINAL_RATIO_OUTSIDE_BUDGET、SEMANTIC_QC_UNAVAILABLE（缺FILM_RECAP_BASE_URL）各1项。postQC **DEGRADED**：SUBTITLE_READABILITY_RISK 5项、VISUAL_REVIEW_NOT_VERIFIED与AUDIO_REVIEW_NOT_VERIFIED各1项；均按原QC非阻断记录保留。没有调用模型/TTS/付费服务，不能把渲染完成改成整体PASSED。

- 声明30.8–34与34.5–36秒，同Beat同源，得到RECORDED_WINDOW_FULL。
- 在**同一实际输出**上改声明为30.8–34与40–44秒，得到PARTIAL，后者覆盖40–42，缺42–44。不是另渲染一部截短片；原43秒的时间跳跃不在此输出内，不据字幕合并条推断连续因果。
- 未知Beat请求被拒绝，不宣称真实移动Beat输出已测。无render/非增量缺记录的UNKNOWN正例保留。

最终MP4 SHA `185925478cb70cfcbf03ad048f27850154eb972ddd6449d1fd6395d1c3c636d8`（1,290,235字节），完整解码无错；实际仅看5秒与10秒两张静帧，见两人在桥栏旁、后一帧机械手臂伸向另一方，不推断台词/关系/因果，未听审。预览前后workspace字节/源SHA不变，87个film与顶层runtime源码摘要与冻结版一致；不因这些技术结果认证语义。

完整本地证据为`reel-stage13-film-evaluation/final-v4/report.json`、实际阶段QC、render_plan/receipt、source-code-identities及README；早期BLOCKED/UNKNOWN均未删除。17秒640×360 safe-fit-blur原声测试派生不是完整中文解说交付，素材不入仓，对外提供须署名Blender Foundation、注明改动及CC BY3.0来源。
