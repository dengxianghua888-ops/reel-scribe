# 中文否定录音：整段保护与恢复，不是逐词剪辑验收

本切片接续 #23 `f944210cb7981e1530f05c38f82f3ba1326ec911`，最终代码身份以集成提交报告为准。

来源是 Google FLEURS cmn_hans_cn validation 的 id1640 录音，固定数据版本 `70bb2e84b976b7e960aa89f1c648e09c59f894dd`，CC BY4.0。原始WAV SHA256：`9517fcaf0f74eaa21083438b52c5a36efdef0c2c6473be21c1315af153e19d56`。参考文本为数据集标注，未由本次听审确认：

> 在冰雪覆盖的路面上，摩擦力很小，你不能像在光洁的柏油路上一样开车。

## 实际做过的事

1. 原WAV保持不动。明确生成960×540、25fps纯色测试画面，音频原流复制到PCM MOV，完整13.92秒。它不是真实讲话人画面。原WAV与承载MOV的16kHz单声道float PCM全解码字节一致，摘要均为 `dfffd3e5e569b9fe4115df70925592836daa1091860fea283f81593fe0ff4f0e`。
2. 字符比例估计时间保持`estimated`身份。既有speech编译器及新增brief入口均实际拒绝它作为剪点；新入口未生成prepared请求，原Work不变。不通过改timing标签或捏造词边界凑验收。
3. 在独立Work声明整段警告音频源窗必须保留。试图截掉末尾1秒的候选被`EVIDENCE_TRUNCATED_REORDERED_OR_REPEATED`拒绝。这验证声明范围保护，不证明系统自动定位了“不能”。
4. 明确只调整字幕包装；原plan、字幕全文、音频、notes和保护保持。旧版本提交被CAS拒绝。再恢复原版，文档逐项相同且历史产生新版本，原始素材不动。
5. 原版、包装版、恢复版都实际渲染并完整解码。输出是AAC、48kHz双声道，三者解码PCM摘要相同（`4d9675d44504190352f893ccbc8aea9721b159d66cf03867aa662965bda4041c`），但**不等于原WAV**；原声采样率转换及有损编码不得称无损成片。原版和恢复版视频文件摘要也相同。
6. 查看原版/包装版2秒帧，参考全文及“不能”可见。这是单帧字幕检查，不是全程看听。

## 未完成

真实逐词对齐、否定词声学位置、删词接点、真实语义和听感都为NOT_RUN。全句源窗保护不等于词级精剪；比例估时不能升级为金标。新brief请求准备器也不能以字段齐全替代这些判断。采用编译计划须经timeline-revise，重新核当前Work和字幕/音轨/持久保护映射，不能直接覆盖plan。

本地验收目录 `reel-mandarin-protection-20261112` 保留源/派生哈希、命令、回执、三输出和失败；不随源码打包媒体。署名：Alexis Conneau 等（2022），FLEURS: Few-shot Learning Evaluation of Universal Representations of Speech，[数据卡](https://huggingface.co/datasets/google/fleurs/blob/70bb2e84b976b7e960aa89f1c648e09c59f894dd/README.md)，[CC BY4.0](https://creativecommons.org/licenses/by/4.0/)。变更为合成画面、字幕和包装/编码；不表示原作者背书。
