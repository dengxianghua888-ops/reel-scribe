# 本地领域检查

这些命令来自库根的 `scripts/drama_tools.py`，可只用 Python 标准库运行，不要求安装 Agent、Provider 或媒体模型。它们消费本入口的领域附件，不是自动导演或渲染器。完整本地约定见[本地验证与采用](../../../contracts/drama/03-本地验证与采用.md)。

在分发包根目录执行：

```sh
python3 scripts/drama_tools.py validate workflows/raven-drama-production/examples/return-key/drama-content.json
python3 scripts/drama_tools.py context workflows/raven-drama-production/examples/return-key/drama-content.json --scene SC02 --budget-chars 32000
python3 scripts/drama_tools.py variant workflows/raven-drama-production/examples/return-key/drama-content.json workflows/raven-drama-production/examples/return-key/variant-FB01.json
python3 scripts/drama_tools.py impact before.json after.json
```

`before.json`、`after.json` 是同一故事修改前后的真实输入文件，需由调用方提供。命令可加 `--output FILE` 保存独立结果，已有结果不覆盖。上下文预算单位是 Unicode 字符，不是 token；超限明确报错，不默默丢掉必须条件。

结果中的结构或声明 PASS 仅限列明规则。语义疑点保持 UNCERTAIN，并保留对象、依据和复审范围；画面、音色、表演与完整看听仍是 NOT_RUN，除非另有真实审查记录。变更影响是候选范围；没有实际消费绑定时不宣布真实文件失效或节省了生成费用。

《归还钥匙》的 JSON、上下文与闪回文件保留冻结设计值。它们描述拟议剧情，`fixture_assumed`、`design_candidate` 不是当前作品采用记录。示例 `review_scope` 中提及的设计复核属于原研究包来源，不能用它代替本次运行回执；执行这些命令会产出新的结果。

需要挂载真实本地 Work 时，先用 `verify-package MANIFEST` 核附件，再以 `prepare-attachment MANIFEST --store /absolute/existing/work.sqlite3 --base-version TOKEN` 准备不可变附件与 notes 引用。准备成功没有提交作品，接着仍走既有 `timeline-revise`、`work-version commit` 和实际读回；不得另造 adopt 指令绕过范围与版本校验。

本入口注册为 W17，不扩张旧 W01–W16 评测名册的分母。剧情试点的新名册见[评测范围约定](../../../docs/evaluation-roster-v2.md)。
