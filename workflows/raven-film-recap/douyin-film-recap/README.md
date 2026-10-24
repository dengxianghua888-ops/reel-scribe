# 影述 · Reel Scribe：影视解说子集

> 本入口属于 [影述 · Reel Scribe](../../../README.md) 的[影视解说工作流](../SKILL.md)。当前 Python 候选版本为 0.3.0，工作区协议为 Schema 2；原 0.2.0 数据须显式迁移。

> 把一部电影或一集剧，变成有证据、可修改、能交付的中文影视解说。

`douyin-film-recap` 是一个开源 Agent Skill 与本地制作流水线，面向 Codex、Claude Code、Cursor 等 Agent 环境。它从字幕、镜头和原片证据出发，完成故事理解、高光召回、解说方案、可编辑分镜、旁白、字幕、竖屏渲染和质量检查。

它追求的不是把剧情摘要铺满画面，而是让旁白、原声、动作、表演和停顿各自承担合适的任务。

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![License MIT](https://img.shields.io/badge/License-MIT-2ea44f)
![Version](https://img.shields.io/badge/version-0.3.0-8A2BE2)
![Tests](https://img.shields.io/badge/tests-80%20passed-brightgreen)

## 它能做什么

| 阶段 | 能力 | 主要产物 |
|---|---|---|
| 理解素材 | 字幕 / ASR、镜头索引、人物、事件、因果、揭示顺序 | Transcript、Scene Index、Story Graph |
| 找到戏眼 | 召回冲突、动作、台词、表演、情绪、反转、喜剧和关系变化 | 高光候选与保留理由 |
| 设计讲法 | 主线、钩子、Beat、剧透策略、旁白与原声分工 | Recap Plan |
| 编译分镜 | 为每段旁白绑定真实镜头，为原声保留完整动作与句界 | Storyboard、可读脚本 |
| 生成成片 | 分段 TTS、竖屏适配、原声底音、中文字幕、FFmpeg 渲染 | MP4、SRT、预览 |
| 验证交付 | 来源、时间、帧率、编码、字幕、实际消费镜头和视听证据 | EDL、QC、交付报告 |

可以只运行到任意阶段。找高光不必生成配音，只要方案不必渲染成片。

```mermaid
flowchart LR
    A[影片 / 剧集 / 字幕] --> B[镜头与对白索引]
    B --> C[人物 · 事件 · 因果]
    C --> D[多类型高光]
    D --> E[主线与 Beat]
    E --> F[可编辑 Storyboard]
    F --> G[TTS · 原声 · 字幕]
    G --> H[竖屏成片]
    H --> I[EDL · QC · 交付报告]
```

## 为什么值得用

### 1. 先理解故事，再动剪刀

系统分开记录源素材时间、故事发生顺序、原片揭示顺序和成片时间。人物身份、关系、关键因果和钩子都必须能回到素材证据，减少悬疑片提前泄底、群像人物混淆和“旁白自己编动机”。

### 2. 高光不只是音量峰值

它会寻找动作和冲突，也会寻找演员表演、反应、沉默、喜剧节奏、人物选择、关系变化与道德代价。每个候选都保留上下文、最小完整边界、剧透风险和取舍理由。

### 3. 原片负责出刀，旁白负责连接

旁白压缩背景、跳时和重复过程；原片保留无法被复述替代的台词、动作、停顿与情绪。普通配画也必须来自已分析镜头，不能在宽泛时间范围里“猜一个画面”。

### 4. 能恢复，也能让人接手

流水线有阶段缓存和输入指纹。改字幕会让相关下游失效，改一段旁白只重做受影响内容，人工修改过的 Storyboard 可以继续使用。`edit_decision_list.json` 记录最终真正消费的源片范围。

### 5. 不把能播放当成已经做好

质量状态分为 `PASSED`、`DEGRADED`、`BLOCKED`。文件存在、FFmpeg 返回 0 或模型说“看起来不错”，都不能代替画面与声音检查。没有独立视听证据时，成片不会被标成完整通过。

## 5 分钟开始

### 1. 安装

```bash
git clone https://github.com/dengxianghua888-ops/reel-scribe.git
cd reel-scribe/workflows/raven-film-recap/douyin-film-recap

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[all]"
```

系统还需要 FFmpeg / ffprobe。烧录字幕时，FFmpeg 必须包含 `libass`，并提供可读取的中文字体。

### 2. 注册为 Agent Skill

```bash
python scripts/install_skill.py --agent codex
# 也支持 --agent claude 或 --agent cursor
```

### 3. 配置模型

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

在 `.env` 中设置 OpenAI-compatible LLM / VLM 服务：

```dotenv
FILM_RECAP_BASE_URL=https://your-endpoint.example/v1
FILM_RECAP_API_KEY=replace-me
```

再在 `config.yaml` 中选择模型、ASR、TTS、目标时长、画幅和素材权利确认。

### 4. 检查环境并运行

```bash
python -m douyin_film_recap doctor --config config.yaml

python -m douyin_film_recap run "/path/to/movie.mp4" \
  --work-dir "./work/movie-demo" \
  --config config.yaml --allow-remote
```

只想先看高光：

```bash
python -m douyin_film_recap run "/path/to/movie.mp4" \
  --work-dir "./work/movie-demo" \
  --config config.yaml \
  --until highlights --allow-remote
```

修改分镜后，从配音继续：

```bash
python -m douyin_film_recap run "/path/to/movie.mp4" \
  --work-dir "./work/movie-demo" \
  --config config.yaml \
  --from-stage tts --allow-remote
```

## 内容模式

上述 `--allow-remote` 用于传递用户已授权的本次阶段范围；相同绑定的有效授权可复用。API Key 本身不表示授权，未知提交不自动重发。旧数据迁移、固定只读 B 包、恢复与本地请求上限见[工作区协议](../../../docs/film-workspace-v2.md)。本地技术回归通过不代表客户端安装或真实影视质量已验收。

| 模式 | 建议时长 | 适用内容 |
|---|---:|---|
| `highlight` | 30–90 秒 | 一个名场面、表演或动作高潮 |
| `short` | 3–6 分钟 | 单集、单线、强高光内容 |
| `standard` | 6–10 分钟 | 大多数电影与电视剧单集 |
| `deep` | 10–20 分钟 | 复杂悬疑、群像、长程剧情 |
| `auto` | 自动选择 | 根据人物、事件、反转和素材长度决定 |

内容单位与时长分开。你可以讲一个场景、一段关系、一集、全片或一个系列 Part，也可以用 `project.editorial_brief` 指定核心问题、叙述立场、观众知识、必须保留内容和剧透策略。

人物线、关系线和主题沿用 `editorial_brief.narrative_question`、`preserve`、`stance` 以及计划中的 `pov`、`main_spine` 表达。人物分析完成后，Beat 的 `character_focus` 绑定注册表中的 `character_id`；显示名、别名和临时身份不会自动合并或替换 ID。旧配置无需增加字段。

规划结束时统一检查各 Beat 的 `event_ids`、`character_focus` 和 `preferred_highlights`。引用缺失于本次提供的注册表时，错误列出 Beat、字段路径和 ID；手改计划也会在 pre-QC 检查。临时/歧义身份、缺证据映射、未建立的人物/高光事件联系保留为 `unknown`，新计划在现有 `risks` 中记录，不把上下文用法当作事实矛盾。R1 的请求记录还保留引用诊断；未知或重复事件 ID 不增加揭示许可。有效引用和 `candidate_evidence` 均不证明事实正确、跨集证据齐全或已经进入成片，剧透约束仍由原有规则执行。

## 交付物

完整运行会保留：

```text
state.json                         断点与阶段状态
07_highlight_candidates.json       高光与证据
08_recap_plan.json                 主线、钩子与 Beat
09_storyboard.json                 唯一剪辑执行依据
output/final.mp4                   最终视频
output/preview.mp4                 预览视频
output/master.srt                  成片字幕
output/edit_decision_list.json     实际消费镜头
output/delivery_report.md          质量与交付边界
```

## 验证状态

v0.2.0 已完成 80 项自动测试，并用真实 FFmpeg 对合成素材验证导入、竖屏渲染、原声与旁白混音、中文字幕和 EDL。测试不调用付费模型，也不上传影片。

真实长片的故事、人物、高光和审美质量仍需要合法素材与人工金标评测。项目不会把合成回归说成生产级内容质量。完整边界见 [VERIFICATION.md](VERIFICATION.md)。

## 项目结构

```text
douyin-film-recap/
├── SKILL.md                 Agent 入口与阶段路由
├── src/douyin_film_recap/   本地运行时
├── references/              故事、高光、节奏、QC 协议
├── schemas/                 结构化产物 Schema
├── evals/                   内容评测模板与就绪检查
├── tests/                   确定性与 FFmpeg 回归
└── scripts/                 安装、Schema 与评测工具
```

## 参与贡献

欢迎提交 Issue、改进文档、增加 Provider、补充合法评测案例或修复运行时问题。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

尤其欢迎这几类贡献：

- 更可靠的人物身份与非线性叙事理解
- 不同题材的高光与节奏评测
- 中文字体、ASR、TTS 和跨平台兼容
- 可回放、可比较的真实内容金标

## 边界

- 只处理你有权使用的素材；项目不提供影片下载、去水印、版权规避或自动发布能力。
- 生成技术不自动授予发布或商业化权利。
- 项目不承诺流量、爆款或免人工复核。
- 当前为可安装、可继续开发的 MVP，不是无人值守的内容工厂。

## 可选离线对齐结果接入

已有字幕可以导入绑定源媒体/字幕哈希的逐词时间证据，默认关闭；不安装或运行声学模型。缺字、插值或重叠字幕保留整句估算边界。实际命令、WhisperX原生字符转换和限制见[对齐结果接入](docs/alignment-import.md)。合成契约测试不代表真实中文语音收益。

## License

[MIT](LICENSE)
