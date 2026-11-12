---
name: creation-brief-prepare
description: 将 Agent 已明确解析并标注出处的创作简报关联到当前 Work，准备已有字幕包装或教程校验请求，列出缺项；不自动理解原话、推荐风格、渲染或提交。
---

# 显式简报准备

遵守[创作简报合同](../../contracts/creation-brief-contract.md)及[路由协议](../../registry/router.md)。从用户已给内容与可用上下文解析字段，不要求用户重复填表；解析判断仍由 Agent 负责。

传原话、场景/模式/明确意图、逐字段来源、当前 Work/version 与明确参数。参数齐全的现有原子操作不必经过此入口。此入口用于交接与材料检查，不建立新的作品。

首版只准备 `style-recipe-preview` 的字幕呈现受限请求或 `tutorial-plan-compile` 的当前计划校验请求。PLAN/ANALYZE仅交报告中的不可执行草案；缺词级对齐不能冒充精剪，未明确叙事不能用风格标签生成镜头。

即使 `READY_FOR_DOWNSTREAM_VALIDATION` 也不等于下游通过或用户授权已验证。执行前重读当前头、核用户实际意图及权限，调用原有操作验证。教程编译器没有Work CAS，成功只验证固定计划，不能当作当前作品已修改。
