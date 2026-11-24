# 影述 · Reel Scribe：项目介绍与对外文案

本页集中存放仓库首页以外的对外文案：GitHub About、Topics、社交预览图和版本发布说明。改动首页定位时，这里同步更新。

## 一句话介绍

让 AI Agent 像剪辑师一样剪视频：看懂素材、写出剪辑方案，调色、字幕、声音一步步做出来，说一句话就能精准地改。

English: Let your AI agent edit video like an editor: read the footage, plan the cut, grade, caption and mix step by step, and change exactly what you ask in plain words.

## GitHub About

在仓库首页右侧 About 旁的齿轮里填写。

- **Description**（中英双语，约 160 字符）：

  影述 Reel Scribe｜给 AI Agent 的视频剪辑技能库：17 条场景工作流 + 52 个原子操作，剪辑方案、一句话调色、相机 Log 还原、字幕与局部修改。Video editing skills for AI agents.

- **Website**：`https://github.com/dengxianghua888-ops/reel-scribe/blob/main/README.en.md`（英文首页）。没有独立网站时可以留空。
- 勾选 **Releases**，取消勾选 **Packages** 和 **Deployments**（仓库没有发布包和部署）。

## Topics

GitHub 最多 20 个。保留原有 12 个中仍然准确的，补上调色和 Agent 相关的检索词：

`video-editing` `ai-agents` `agent-skills` `claude-code` `codex` `mcp` `mcp-server` `color-grading` `lut` `subtitles` `ffmpeg` `opencolorio` `movie-recap` `editing-workflows` `douyin` `tts` `python` `chinese`

原有的 `agent-skill` 与 `agent-skills` 重复，去掉单数形式。

## 社交预览图

在 Settings → General → Social preview 上传 `docs/assets/readme/social-preview.jpg`（1280×640）。分享仓库链接到微信、X、Slack 等时会显示这张图。

## 发布介绍

一段口播，重点是保住观点和自然停顿；一支教程，要让人看清每一步；一段影视解说，要处理人物、因果和揭示顺序。让 AI 动手剪之前，先要让它知道这次为什么这样剪。

「影述（Reel Scribe）」把这些方法整理成 AI Agent 能直接执行的场景工作流和原子操作。你说“暖一点”“这句字幕别动”“最后那个镜头别碰”，Agent 会把它变成可复现的参数和明确的修改范围；调色、Log 转换和作品渲染完成后会读回成片核对。

它适用于 Claude Code、Codex 等能读取本地文件的 Agent，可以接入你已有的剪辑工具，也可以用库里自带的本地执行器。

项目地址：https://github.com/dengxianghua888-ops/reel-scribe

## 版本发布说明草稿：v0.4.0-alpha.1

建议标签 `v0.4.0-alpha.1`，标记为 Pre-release。以下内容可直接粘贴到 Release 描述：

> **影述 v0.4.0-alpha.1：调色层与新首页**
>
> 自 v0.3.0-alpha.1 以来的主要变化：
>
> **🎨 调色层（全新）**
> - 一句话调色：“暖一点”“对比强一点”等说法按映射表换成白平衡、曲线和饱和度参数，并逐项校验方向（`color-grade-adjust`）。
> - 调色编译：曝光、白平衡、ASC CDL、曲线、HSL、高光滚降和 LUT 编译为 cube，并导出 `.cc` 和 CLF（`color-grade-compile`）。
> - 参考图拟合出可编辑的调色参数草案（`color-reference-fit`）；镜头间保护区域一致性检查，不达标就不出片（`color-consistency-check`）。
> - 相机 Log 还原：Apple Log、S-Log3、V-Log、ARRI LogC、Canon Log、D-Log 等，可用固定版本的 OpenColorIO 配置或厂商官方 LUT（`color-log-transform`）。手机 HDR（HLG/PQ）转 SDR（`color-input-transform`）。
> - 胶片质感：光晕、颗粒、暗角（`film-texture-apply`）。
> - 作品调色：WorkDocument 新增调色层与胶片质感，支持局部撤销、风格配方 A/B 和修改影响分析。
> - Blender Color Balance 调色互通（实验）。
>
> **🎬 工作流与影视解说**
> - 新增剧情创作与制作交接工作流，场景工作流增至 17 条。
> - 影视解说子集新增 OTIO 导出与回读、局部旁白修订、增量渲染缓存和 HTML 报告。
>
> **🛠 可靠性**
> - 运行时与 MCP 支持协作取消与进度；读回检查改为按块比较，真实素材的传感器噪声不再导致误判。
> - 多项修复，详见 CHANGELOG。
>
> **🏠 新首页**
> - 中英文首页、20 秒演示和前后对比，演示画面全部由本库的原子操作生成（素材：Netflix《Sparks》，CC BY 4.0）。
>
> **兼容性提示**：`chat_json` 改用新的意图键；`revision-impact-inspect` 的阶段列表新增 `color-grade`；`color-lut-apply` 分层读回的回执字段由 `analysis_size` 改为 `block`、`block_stride`、`blocks_per_frame`。详见 CHANGELOG 的兼容性说明。
