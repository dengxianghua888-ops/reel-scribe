---
name: style-recipe-compile
description: 将摘要绑定的显式字幕与音轨包装配方编译为受范围保护的作品候选；不自动选择内容、不渲染、不把风格卡当已验证效果。
---

# style-recipe-compile

按[能力交接合同](../../contracts/capability-handoff.md)核对工具，再按[请求合同](../../contracts/style-recipe-contract.md)提供当前作品、版本和显式范围。

本地实现仅处理调用者已确定的参数，不推断自然语言意图、不写入作品库、不调用外部服务。候选需经现有 Work 预览与版本冲突校验后才能采纳；真实内容与效果验收另行记录。
