---
name: result-preview-compile
description: 为当前教程作品前置显式指定的后段结果画面，保留完整原流程，生成带预览与返回标注的范围受限候选；不选结果、不判断因果、不提交作品。
---

# 显式后段画面预览

读[结果预览合同](../../contracts/result-preview-contract.md)。仅当用户已选择信息顺序调整，且上层已核对目标源窗和当前作品时使用。不是自然语言自动选镜或参考视频观察器。

传当前 Work store/expected_version、已固定的结果先行卡、原教程 steps/result_cues、目标 step 的 result 内源窗、预览与返回标注、全部允许后移的 clip IDs 及实际 scope。输出标准 candidate.json，通过既有 work-render preview_candidate 预览；不自动 commit。

操作保留全部原 clips 顺序和内容，前置一段同源1×复制；源窗重复与后移必须明确授权。已有持久保护仅支持原声明/carrier完全不变、显式scope.evidence_mapping:true的统一后移并重新验证；不把preview注册为证据。独立音轨及视觉层仍不支持，保留原作并拒绝，不建议取消保护来绕过。标签冲突/冻结时不静默改字幕或解除冻结。

首版仅 authored-mechanism-only，不声称真实参考视频迁移、因果验证、操作复现或教学效果。参考观察与逐项采纳继续由[参考工作流](../../workflows/raven-reference-style/SKILL.md)负责。
