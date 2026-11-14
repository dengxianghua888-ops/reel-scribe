---
name: tutorial-artifact-check
description: 将明确的软件教程结果、后续观察窗口和本地产物字节身份连接成可回查记录，不自动认证画面观察、产物来源或后台持久化成功。
---

# 教程产物检查链

依照[产物检查合同](../../contracts/artifact-check-contract.md)，把已有ExecutionPlan和tutorial步骤、真实本地输入/产物引用、明确观察窗口与观察者原话交给`tutorial-artifact-check`。
先复用既有教程before/action/result校验，再核声明的检查窗口在结果之后且完整保留。

本地产物缺失用`null`，输出INCOMPLETE；不要拿截图、按钮或捏造文件顶替实际产物。
截图本身可以作为“截图这个产物”检查，但其SHA不证明原应用已保存/发表。
正常LINKAGE_VALIDATED仅代表字节与声明时轴连通，不代表用户授权、操作发生、真实重开
或后台状态。`FRAME_DERIVATION_NOT_VERIFIED`及观察真实性未知始终保留。
该入口不修改Work、不生成或采用成片、不设新的发布门槛。工具不联网、不会拉取URL。
