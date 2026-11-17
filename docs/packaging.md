# 当前源码预览的构建与验证

两种构建器使用 [明确成员清单](../contracts/package-members.json)。增加运行模块、Skill 或公开文档时，同步更新清单；未声明文件、开发缓存、临时日志和私有 `.env` 不会因处于某个核心目录而被复制。成员清单只定义包范围，不证明分发权利。分发包不包含开发测试目录；pytest 与回归测试在源码仓库运行。

```text
python3 scripts/build_portable_bundle.py --out /absolute/new-portable
python3 scripts/build_codex_plugin.py --out /absolute/new-plugin
```

输出必须是新目录。合法无扩展名 LICENSE、受控文本格式（包括 TOML）需要通过 UTF-8 与内容检查；可解码的未知类型仍不自动成为文本。当前轻量源码没有 HTML/CSS/JS 资源，不需要资源声明。`portable-resource-edges.current.json` 保留历史 evals 的原 SHA，不是当前公开快照的默认配置；不能改历史 SHA 或创建替代证据来让它通过。便携构建显式选择资源时仍执行原受限声明和分发策略；轻量插件暂不支持附加网页资源，遇到这类成员明确拒绝。

引用检查分为文件依赖、目录导航和资源边。README 的六个目录导航在源码与输出中都验证，但不会递归引入目录下未声明的文件。导航目标必须有已声明入包成员，拒绝越界、缺失和符号链接，也不会为通过检查创建空目录。链接到新增文本需要先将文件加入成员清单。

检查覆盖所有最终入包 Markdown（含 README、AGENTS、docs、skills 和许可通知），并核插件、MCP、registry 的明确入口。受限 Markdown 解析器忽略代码中的示例；参考式链接和 HTML 标签引用目前明确报错，新增这些语法需补解析与测试，不能静默跳过。

构建前后核每个文件的 SHA、字节和 POSIX 模式，复制后核最终成员与引用；失败输出保留 `build-incomplete.json`，不会写成功清单。清单按路径排序，重建比较成员和摘要，不将本地构建当作客户端安装。符号链接检查覆盖静态祖先；不宣称抵抗同权限进程对输出目录的恶意并发替换。

在输出目录分别运行 `python3 scripts/verify_library.py structure`、`scripts/install_doctor.py --root <包目录>` 和实际 stdio 调用。将包迁移到包含中文和空格的新路径，使用输出自身脚本及新工作目录，清除原 checkout 的 `PYTHONPATH` 和库根配置。缺依赖继续记录未知或未执行；固定 helper、实际客户端安装和真实作品验收各有独立要求。

两类成功状态仍分别为 `BUILT_NOT_HOST_INSTALLED` 和 `BUILT_NOT_INSTALLED`。构建过程不联网、不付费、不修改用户 marketplace。

## 版本号的含义

仓库内几个版本号各自标识不同对象，不需要相同，也不互相推导：

| 版本 | 位置 | 标识对象 |
|---|---|---|
| `v0.3.0-alpha.1` | `CHANGELOG.md` | 整个技能库源码预览的发行条目 |
| `0.3.0` | 影视子集 `pyproject.toml` | `douyin-film-recap` Python 包 |
| `0.17.0-dev` | `runtime/editing_runtime.py` 的 `VERSION` | 本地执行器；写入每份 receipt 的 `runtime_version`，随操作协议演进 |
| `0.1.0` | `.codex-plugin/plugin.json`、MCP `serverInfo` | 插件与 stdio MCP 桥接；客户端安装验收前保持 `0.1.x` |

发布新的库条目时，在 CHANGELOG 记录这几个组件当时的版本；单独修改某个组件时，只提升该组件自身的版本号。
