# 控制器中断、无最终回执恢复：有界真实验收

不修改仓库代码。使用冻结隔离运行时 reference_transfer_ops.py `1bd5cf5ba2ed7ec119e5841803e1b07d617f3ac1bcb0b7914af642d96ee03c7d` 及其46个运行时文件，既有CC BY-SA WikEd六秒输入、两任务（原样与一条字幕呈现调整）。测试副本初始化为新 Work，不调用历史源 Work。

## 注入与安全范围

外层启动自己的独立session控制器。仅当第二任务实际 FFmpeg 创建非零 MP4（48字节）时，其 Popen 观察线程记录自身控制器PID、子PID/PGID和命令，并SIGSTOP自身。外层核实该已知子进程PID=PGID，先SIGTERM该独立FFmpeg组，确认退出或僵尸状态（文件描述符已关闭），然后SIGKILL自己的已停控制器并wait。没有杀其他工作进程。模拟的是控制器中断且无最终回执，不是停电/机器崩溃；没有把孤儿继续渲染当恢复成功。

## 验收事实

- 第二任务原attempt存在真实残留、无最终receipt。新调用使用 `retry_failed=false`，识别 `INTERRUPTED_ATTEMPT_PRESERVED` 后新attempt2成功；这是RUNNING无回执转PENDING的恢复，与FAILED默认不重试分支不同。
- 第一任务 `REUSED_VERIFIED`，未重渲染。
- 队列中原attempt1状态INTERRUPTED，错误为lock released and no final receipt；其全部原文件字节未变且始终无最终receipt，不当作成功。
- 第二任务attempt2为RENDERED。两任务均与另起独立冷渲染的全程RGB/PCM摘要一致；视频文件摘要逐一重新核验。
- Work完整状态、输入源摘要与46个运行时文件保持不变。20份实际回执的运行时来源摘要全部匹配。
- 耗时：控制器启动到中断10.082秒；恢复6.962秒；两冷渲染4.225/5.510秒。不据此声称普遍加速或成本节省。

报告 `evidence/report.json` SHA256 `344d8df909fcb3633f853f490cb59b24183122117b5efb4a273f1b8175f48eae`。
补充审计 `evidence/post-audit.json` SHA256 `4a733d527f42f9fe8dfd2b48014f30962094c87c90b53563861fd5b1c2bea1d5`。

这项验收证明一次有界真实中断恢复，不覆盖磁盘满、断电、数据库损坏、网络或远程服务；没有连续观看听审、语义质量或真实用户认可结论。源素材署名与许可沿用既有fixture登记。本记录补充恢复验收，不改变既有失败分支结论。

素材署名：Nikkimaria，WikEdtutorial1，CC BY-SA 3.0。固定来源 https://commons.wikimedia.org/w/index.php?title=File:WikEdtutorial1.webm&oldid=1131672871 ，许可 https://creativecommons.org/licenses/by-sa/3.0/ 。六秒规范化输入来路及区别于本次的FAILED分支实验见[前一恢复验收](real-failed-render-recovery-20261112.md)。
