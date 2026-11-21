---
name: timeline-revise
description: 比较当前作品文档与明确候选，在显式片段、字幕、音轨、风格和备注范围内校验增删重排或参数修改，输出差异与失效项；不解释审美反馈、不自动选段、不提交作品。
---

通用调用先按[能力交接合同](../../contracts/capability-handoff.md)核对当前 Agent 的读取、执行和读回能力。下文的操作名、严格字段、路径和本地执行器只约束选择本库实现的路径；使用其他工具时保留目标、范围、保护项与结果核对语义。

# 有范围的修改候选

按 [作品合同](../../contracts/work-contract.md) 提交当前文档、基础版本、候选和 scope。复杂层负责所有内容与范围决定；原子层不把“更紧凑”转换为自动删减。

未列入允许清单的片段内容与相对顺序保持；freeze_positions 进一步锁定输出起止帧，freeze_duration 锁定总帧数/帧率。冻结源内容不等于冻结时间位置；两者由用户意图分别确定。

新增/删除字幕、音轨、风格与备注需各自授权 ID。重选镜头时，锚定其上的字幕和音频要在复核范围内，不能仅凭相对时间还合法就宣称仍与内容一致。来源替换不得通过同 source_id 绕过其他冻结片段。

可选 scope.grade_ids、scope.color_inputs、scope.color_checks 控制调色层、输入解释、调色保护项与上限的变化，调色层覆盖的源内容改变时也须列入 grade_ids（见[作品调色合同](../../contracts/work-color-contract.md)）。可选 scope.visual_ids 控制 visual_layers 的增删改；层覆盖窗口下主轨源内容改变，或全局几何变化时，受影响层须列入复核范围。

已有 evidence_protection 随作品保留，不能在候选中连声明一起删除或改写。需要重排承载对象时，可用布尔 scope.evidence_mapping 开放 occurrences/chapters 修改，覆盖和依赖仍须成立；units/required_units 不在普通修改范围。保护变更是独立 work-version set-protection 操作，由上层依据真实意图决定。预览不读取 SQLite，最终 commit 会用数据库当前头重新核基础和保护；伪造预览基础不能当作采纳成功。

输出 candidate.json 和 revision-diff.json；作品不会被改动。候选可经现有渲染原子生成预览，已授权清晰任务也可直接调用 work-version commit，再用 work-render 导出该版本。不能把候选文件存在当修改已经应用。
