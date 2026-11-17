# 结果预览与持久保护共存：有限实现与验收

本切片接续PR #23 `8c4da2ada780d1a278146c44d990e9b8f4d3ee6c`（本地等价 `f259b445f69cf912ac8c799019f1ed9c488cd2ea`），最终提交身份由集成报告另行绑定；不是默认分支已发布声明。

## 做了什么

`result-preview-compile` 允许已有合法持久保护在明确 `scope.evidence_mapping:true` 下随完整原流程后移。原units、requires、required_units、occurrences、carriers、dependencies和chapters声明完全不变。源窗与原clip身份不变；只有从当前时间线派生的输出区间统一后移。新preview没有注册为保护实例，不能代替原动作或结果证据。

导入原Work后立即检查权限与不支持项。先验证每个旧clip的输出起止帧增加精确预览帧数，再调用既有ordinary_protection算法校验前后每个part源时钟/速度不变、输出有理时间增加精确时长，随后才生成candidate。独立音轨、视觉层、变速仍拒绝。最后重核保护来源、证据、卡片和Work版本。普通声明范围保护不升级为strict SOURCE COMPLETE、像素/样本冻结、语义或听感通过。

## 测试与真实许可素材

定向 `tests/runtime/test_result_preview.py` 33项通过，包括原声明/依赖/章节、显式映射授权、原位置/总时长冻结、缺输出scope、删required/unit、把carrier改到preview、删原clip/换源、证明失败先于candidate、末尾来源变化无成功报告。注入内部候选篡改的测试是防回归哨兵，不是声称存在对外任意候选参数。

真实实验复用既有许可WikEd教程的显式归一化副本，在**新的评估Work**登记before/action/result三个video单元和前置依赖：

| 单元 | 原输出区间 | 加4秒预览后 | carrier |
|---|---|---|---|
| before | 0–2 | 4–6 | 原full-process |
| action | 16–25 | 20–29 | 原full-process |
| result | 36–40 | 40–44 | 原full-process |

原章节声明仍引用这三个原occurrence；派生章节范围由0–40变4–44。前置preview为36–40源窗，输出0–4，但未成为“result-original”的carrier。候选保存全部40秒原流程，原Work保持不动。

最终冻结代码真实编译和work-render预览均成功，44秒输出已完整解码；与未登记保护、相同内容布局的既有helper输出逐帧解码校验比较，用于验证新增保护没有改变声画内容。此前helper的2秒/5秒图像观察可作为相同画面参照，不据此声称本片全程人工观看。音频未听审，声明的before/action/result取自调用者人工标注，不证明因果或陌生用户能完成教程。

评估本地目录`reel-protected-result-evaluation-v2`包含请求、未提交Work副本、两份保护映射、candidate与真实preview；媒体不入仓/不外传。源归属为Nikkimaria / WikEdtutorial1，[固定Commons页面](https://commons.wikimedia.org/w/index.php?title=File:WikEdtutorial1.webm&oldid=1131672871)，CC BY-SA3.0。衍生做了归一化、短窗、黑带/标签与预览重排，不代表作者背书；对外分发须保留归属/变更和相同许可。

## 仍未完成

无自动理解证据或遗漏前提发现；没有参考视频观察/迁移；未支持独立音轨/视觉层重映射。完整看听、真实教学及整卡风格效果仍未验收。保留这些边界，不建议关闭保护绕过。
