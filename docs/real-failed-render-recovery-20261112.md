# 真实字幕渲染失败后的显式恢复（技术验收）

本实验仅在独立测试目录运行，无仓库代码修改，无用户电脑访问。绑定第十四批本地 1fe242263f645dc6bc1e9f85e2da620082efc2be 的 46 个运行时文件。素材沿用 Nikkimaria 的 WikEdtutorial1，CC BY-SA 3.0，原片 25–31 秒显式规范化输入；两句中文字幕是示范标注，不是转录。来源 https://commons.wikimedia.org/w/index.php?title=File:WikEdtutorial1.webm&oldid=1131672871 。归一化输入 SHA256 d2ff21bd999dbc25e9309b7d37d4a062510ba79bc03e30497e32678925110119 。

## 实际执行及结果

- 两任务队列：基础字幕版本、仅首句样式变化版本。第一任务完成；第二任务真实 FFmpeg 已写出 48 字节 MP4 时，测试钩子向该次自己启动的进程发送 SIGTERM。没有伪造失败回执，没有停止其他进程。控制器存活，按正常产品代码生成 FAILED 回执。
- 初次运行事件为 base/attempt1 SUCCEEDED、changed/attempt1 FAILED。外层 run 的 SUCCEEDED 仅表示批次控制操作完成，不代表所有任务成功。
- retry_failed=false：基础任务 REUSED_VERIFIED，失败任务 FAILED_LEFT_UNCHANGED，不产生 attempt2。
- retry_failed=true：基础任务仍 REUSED_VERIFIED；第二任务新建 attempt2 并成功。旧 attempt1 的所有文件逐项摘要不变。
- 失败目录仍存在 preview.mp4 与 captioned.mp4，后者 SIGTERM 后最终为 200612 字节；产品没有因文件存在就采纳成功。
- 两任务最终视频分别与独立冷渲染的完整解码 RGB/PCM 摘要一致，且本样例文件摘要也一致。原 Work 头、源摘要、运行时文件身份保持。

## 实测耗时（本次观测）

prepare 2.954 秒；包含基础成功与第二项被中断的初次运行 11.515 秒；默认不重试检查 1.568 秒；显式恢复 7.205 秒。独立基础/改后冷渲染分别 4.344/5.785 秒。包含校验及哈希开销，负载未控制，不能计算通用加速、人工节时或生产成本。

## 边界与保留失败

这次是实际 FFmpeg 子进程中断，控制器存活并保存失败回执；不是控制器崩溃、机器重启、磁盘满、网络失败或跨进程无回执恢复。源码中 RUNNING 且没有最终回执的恢复分支会保留 INTERRUPTED attempt 后回到 PENDING，与本次 FAILED 默认不重试的路径不同，未测路径不补填通过。Fontconfig 缓存告警保留，不误当本次 SIGTERM 的根因。没有连续观看、听审、内容语义或用户偏好验收。

第一轮测试钩子错误地按调用者目录监视相对输出路径，未发送任何终止信号，两个渲染完成后断言失败。这是测试夹具失败，不是产品恢复失败；旧 evidence 和 run.log 保留。修正路径解析后另建 evidence2，不覆盖旧实验。

权威报告：evidence2/report.json，SHA256 2cbb358f03bb188ceb196d4259f2441dcc773218f680b0b93ba75211dcbef381 。执行脚本 run2.py；完整失败/默认保持/恢复事件及输入输出回执保留于 evidence2。素材及改编遵循 CC BY-SA 3.0；独立代码许可不因此改变。
