# 文字对照合同 v1

`operation=transcript-reference-compare`。按[通用合同](operation-contract.md)运行。请求必须包含`document`、`expected_revision=runtime.fingerprint(document)`和`normalization`（`exact`或`whitespace-only`）。只输出文字报告，不修改输入或作品。

document字段：

- `schema`: `text-comparison/1`。
- `source`: 原媒体的绝对path与SHA-256。
- `audio_stream`: 真实音轨绝对索引；`window`: `[源起秒,源止秒]`，必须在实际媒体时长内。
- `language`: 明确语言。
- `reference`、`observed`: 均包含`role`、`artifact`、`pointers`、`joiner`。

每份文本的`artifact`是UTF-8 JSON文件的绝对path与SHA-256；`pointers`是非空、有序、不重复的RFC6901 JSON指针，每个指针必须指向字符串。`joiner`显式指定拼接字符（最长4个Unicode码点）。如公开语料可选择`/rows/0/raw_transcription`，识别原稿可选择`/segments/0/text`及后续明确字段，不能把示例字段当所有文件的通用结构。role允许`corpus-reference`、`user-script`、`model-observation`、`human-transcript`，属于调用者声明，不认证其权威或听检状态。

文件最多32MiB，每侧拼接文本最多20000码点，两侧长度乘积最多4000000；超限显式分窗口／语义段运行。所有选取范围写入报告，不暗中截断。JSON 读取受32MiB上限约束，核对 SHA-256 后从同一份 UTF-8 字节解析；读取期间文件增长也会拒绝。每次处理前后继续复核原文件哈希；这不是持续文件锁或对同用户进程的隔离。文档、字段、窗口或身份任何变化均使expected_revision失效。

输出`text-comparison.json`保留两侧原文、来源、字段到拼接文字的范围、比较规则、差异和原字符半开区间。方向为参考→观察：`insert`是观察多出的字，`delete`是观察相对参考缺的字，`replace`是不同文字。使用difflib.SequenceMatcher且禁用autojunk，结果不是最小编辑距离／CER，不与原FLEURS规范化指标混称。

`whitespace-only`仅忽略Unicode空白，字符映射仍回指原串；不作NFKC、繁简、数字或标点转换。空白忽略后均为空时拒绝。零长度侧只表示文字位置，不赋予声音时间。差异字段为确定性比较，不评判哪侧正确或语义重要性。

共同素材关联由调用者声明；运行验证素材／音轨／窗口和文本文件字节，不认证文本确实对应这段声音或字段已经全选。`source_association`与`audio_truth`明确记录该限制。即使两侧相同，也不能输出已听检、独立对齐或可直接剪辑的结论。用回源证据形成更正稿是复杂层后续工作，旧参考、模型稿和报告不得覆盖。
