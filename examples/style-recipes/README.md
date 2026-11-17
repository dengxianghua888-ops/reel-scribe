# 呈现配方示例

状态均为 **authored-unvalidated**，只映射现有样式卡的一小部分字幕呈现参数，不代表该卡的叙事、停顿或内容策略已执行。无真实作品效果验收。

- `faithful-clean-caption-neutral.json`：忠实轻剪卡的白色字幕呈现候选，不执行删口误或删停顿。
- `guided-first-run-caption-readable.json`：首次上手带练卡的较大暖白字幕呈现候选，不执行步骤识别、镜头聚焦或结果验证。

示例按已有卡片字节记录 SHA-256。把 `/absolute/checkout/` 换成实际助手工作区路径，重新计算整个配方 fingerprint，再提交 `style-recipe-compile`。路径变更同样改变配方摘要。不得将这里的示例字号/边距自动套到任意尺寸视频；以实际画布、字幕内容和遮挡情况选择并预览。没有提供字体和媒体，示例本身不可直接渲染。合同见 `contracts/style-recipe-contract.md`。
