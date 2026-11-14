# 本地证据效率基线（非成本/人工收益）

`scripts/report_benchmark.py` 离线读取显式指定证据根目录内、调用者给出 SHA256 的 `operation-receipt/1`。它重核子回执和声明产物的大小/摘要，按实际 attempt 路径去重，拒绝重复 attempt、冲突快照、重复 JSON key、变更证据和越出证据目录的引用。不读取 Work 数据库、不重新批准历史缓存、不调用模型或媒体工具。摘要不是可信签名，不能识别连同预期摘要一起重写的恶意伪造。

```sh
python scripts/report_benchmark.py --root /absolute/evidence \
  --receipt SHA256=/absolute/evidence/comparison/batch-run/receipt.json > report.json
```

可重复 `--receipt`；同一路径回执只计一次。报告统计已观测尝试、失败及复用事件，保留源窗/源摘要和输出时长。相同媒体被多个候选使用时逐候选报告，不当作独立素材覆盖。没有时间、命令或模型调用记录的历史回执使用 `NOT_RECORDED`，不从文件修改时间估算，不把未发现模型记录说成零调用。缺失失败阶段也不当作零失败，统计范围只含传入且通过摘要校验的回执。状态变更的 attempt 快照请分开报告，不用时间猜测先后。

## 一次可控冷渲染/复用测量

`scripts/run_local_benchmark.py` 是显式执行工具，区别于上面的只读报告器：读取标准 batch prepare 请求，在全新输出目录建立新的队列，按顺序执行 prepare、cold run、reuse run；不修改 runtime、作品头或原素材。调用前须拥有原素材/工作库读取及输出授权，且运行时代码/来源/候选保持稳定。

```sh
python scripts/run_local_benchmark.py --prepare-request /absolute/prepare.json \
  --output /absolute/new-benchmark-directory
```

外层 `time.monotonic()` 测每阶段墙钟时长，包含哈希与验证开销；只在冷阶段为成功 RENDER_ATTEMPT、重复阶段全部为 REUSED_VERIFIED 时称本次测量通过。不承诺通用提速比例。manifest、请求、每阶段回执的摘要关联源/候选/运行时/工具/输出身份。FFmpeg 全调用次数未插桩，保留 `NOT_RECORDED`。模型调用 0 仅表示本工具的本地 batch 路径未调用模型，不是整个系统的审计结果；价格、云费用和人工节省未知。

模型/实际内容/字幕适切性、听觉及用户偏好不在效率指标里。重复实验应新建输出目录，不覆盖原测量。没有完整外层启动/子进程日志时不补填未记录指标。

## 2026-11-12 单次短窗测量（不是性能承诺）

在助手云端使用独立 Work/新候选及新批次，对已明确转换为 30fps/PCM 的访谈说话人 6 秒短窗实际运行：prepare 1.2396 秒，cold run 6.9880 秒，reuse run 1.4709 秒。cold 为一次成功 `RENDER_ATTEMPT`，reuse 为同一 attempt 的一次 `REUSED_VERIFIED`；回执和视频摘要相同。计时包含验证/哈希，未控制系统负载或重复采样，不据此声称通用加速倍数。历史四窗没有计时数据，仍标记未记录。

派生源 SHA256：`d269e525ff3ef82b0956dcf05c521d148c3cbb1d903f72816a04c890687f94cb`。输出 SHA256：`a7eea90d00ddf22c7c87c782fbd3343138c84191a8f1b5385c459b6c184c377f`。原片为 The Green Interview 的 Sir Tim Smit 访谈，CC BY 3.0，固定来源 https://commons.wikimedia.org/w/index.php?title=File:Sir_Tim_Smit,_The_Green_Interview.webm&oldid=1096433542 ，原片 100–106 秒；改动包含截取、显式转码及演示标注。派生媒体和运行证据保留于独立验收目录，不随公开代码包提供；这里不是可直接从仓库重放的媒体基准。

第一次实验 runner 漏传批次合同必需的 job_ids/retry_failed，冷阶段在渲染前被正确拒绝。修复 runner 后另建目录重测，上述数字仅来自第二次成功实验；原失败证据未覆盖，不混算为媒体或 runtime 失败。

## 同机三场景各三次观测

本批冻结运行时代码后，取Tears of Steel原30–36秒、归一化采访原100–106秒、独立字幕带教程原25–31秒；各建立独立Work并使用三个全新batch，不复用旧batch。每组cold为1个成功尝试、reuse为同一尝试的REUSED_VERIFIED；离线重核全部回执/产物，共9个唯一成功attempt和9次验证复用。9组均完成，未发生失败恢复，因此未测失败恢复耗时。

| 场景 | prepare三次秒 | cold三次秒 | reuse三次秒 |
|---|---|---|---|
| 影视6秒 | 1.6733 / 1.3656 / 1.4583 | 12.4614 / 12.8428 / 13.0803 | 0.5670 / 0.5590 / 0.6553 |
| 采访6秒 | 0.6434 / 0.6129 / 0.5856 | 5.1284 / 4.8022 / 5.1713 | 0.3133 / 0.3065 / 0.3292 |
| 教程6秒、独立字幕带 | 0.9440 / 0.8652 / 0.9257 | 5.0814 / 4.9983 / 4.8194 | 0.3094 / 0.3125 / 0.3844 |

冷阶段指新batch首次渲染，不代表操作系统磁盘缓存冷启动。测量时其他测试并行，未控制CPU负载；不同分辨率/源容器和字幕不能横向用来排名性能。各组manifest绑定冻结runtime、工具与来源，原Work头不变；源许可同本轮迭代文档。未测完整长片、模型/provider账单、人工审阅耗时或用户节省。模型调用0仅限这条本地batch路径；FFmpeg总调用数、费用和人工收益继续NOT_RECORDED。证据留在验收目录不随源码打包，不暗示仓库单独包含可复现媒体。
