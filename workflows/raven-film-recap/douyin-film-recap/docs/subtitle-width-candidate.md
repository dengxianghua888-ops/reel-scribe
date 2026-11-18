# 实际字宽断行候选（第一切片）

`python -m douyin_film_recap.subtitle_layout request.json candidate.json`

命令只写一个**新的**候选 JSON，不覆盖已有文件、不修改 Storyboard、SRT、Work 或源素材，不触发模型或付费服务。不自动采用。输入示例：

```json
{
  "cues": [{"id": "cue-1", "start": 1.25, "end": 4.5, "text": "中文 WiFi 速度为 20Mbps。"}],
  "font_file": "/explicit/font.ttf", "font_index": 0,
  "font_size": 24, "width": 360, "height": 640,
  "margin_x": 30, "margin_v": 60, "outline": 2,
  "max_chars": 16, "max_lines": 2
}
```

使用既有 Pillow 的 RAQM 支持测量实际字体 advance 宽度；缺 RAQM、缺 fc-query 字形覆盖检查工具、缺字、缺字体、无可用区域、单个字过宽、不可断长词、超过行数均明确拒绝，不删字、缩字号、改时间或静默切换字体。`font_index` 是集合内明确选择的字面，记录字体全部字节摘要、字面编号、家族和完整参数。没有额外字体下载、安装或新依赖。

候选保留原文、ID、起止时间，只在记录的源文本位置插入换行，原有换行保持。字体和画布变化产生不同身份；不缓存旧布局。字符上限仍然有效；中英混排启发式不是专名、否定关系、语义或33语种排版系统。组合字符、变体选择符和 emoji 肤色修饰暂不支持，小数及单位按整体 token 保护。

## 证据与限制

状态恒为 `CANDIDATE_ONLY`，`adopted=false`。使用 fc-query 检查精确字体字节及字面编号的字符覆盖，缺字拒绝；但该覆盖检查仍不是最终 libass 的边界证明。渲染器可能有字形 fallback、合成粗体、不同字体解析或行高。输出明确 `glyph_coverage=FONT_CMAP_CHECKED`、`render_verification=NOT_PERFORMED`、`human_readability=NOT_REVIEWED`；不得将其报告为 PASSED 或直接当已采用 SRT。

新增回归包括两套 CJK 字体、横竖画幅、中文/英文/数字单位/标点/原空格和换行；独立真实 FFmpeg/libass 合成底图检查可见字形包围盒。测试证明这批固定输入的几何和不变性，不证明任意字形、完整听审或用户阅读体验。

下一切片仍需将候选纳入既有预览/采用/撤销通路，绑定实际渲染字体、显式保护区和最终渲染检查；现有生产路径不自动替换，避免把一次候选原型伪装成完整优化。真实案例、连续听审与编辑器往返沿用现有验收矩阵，未完成项不改为通过。

参考机制：VideoLingo `5b06a8232ca84aec50453442eb16b25c44571c3f` 的测量→拟合→渲染验证（Apache-2.0）。此实现独立编写，没有复制代码或引入上游依赖；字体许可由所选字体单独决定。

## Work preview, adoption and undo

`prepare_work_preview(document, expected_document_sha256=..., store=...,
expected_version=..., recipe=..., caption_ids=[...])` prepares an ordinary
`style-recipe-preview` request with `original` and `measured` variants. It does
not open or mutate the Work store. The equivalent exclusive-file CLI is:

```sh
python -m douyin_film_recap.subtitle_layout --work-preview work-request.json prepared.json
```

Supply the exact current Work snapshot and its canonical SHA-256/version, an
explicit existing compatible style recipe/card and its `layout_constraints`,
and the target caption IDs. No region, style card, source text, or user choice
is guessed. Existing recipe parameters and per-cue overrides are retained;
the normal compiler refuses incompatible/diverged bindings. Preparation pins
the exact font hash/family (collection face zero), effective per-cue size,
canvas, 20-pixel runtime horizontal margins and 1-pixel outline. A different
font face, changed font bytes or stale source snapshot fails explicitly.

The prepared `preview_request` must be executed through the existing Work
runtime. The actual libass layout mask and render receipts, protection scopes,
source bindings and current-version checks remain authoritative. Select a
variant only after inspecting that preview; use the existing preview adoption
command, never copy candidate JSON directly into a store. Adoption and local
undo are the existing Work operations, not new authority in the film CLI.

Breaks are per-cue presentation offsets bound to the UTF-8 source-text SHA-256;
original `text`, anchor and start/end are unchanged. Removing/restoring them is
a presentation operation. Empty offsets mean no inserted breaks. Human reading
preference, film-context suitability, listening and native-editor roundtrip
remain separate unperformed acceptance gates unless actually recorded.

## Separate speed/audio boundary probe (baseline 288521b9)

Cloud-generated six-second media, not a user's film, verified these existing
behaviours independently of the subtitle change:

- A video with no audio stream renders at 0.5x / 1x / 2x into 12 / 6 / 3 seconds,
  with 300 / 150 / 75 decoded frames at 25 fps. No duration-padding fix was
  justified. An unsupported `target_duration` field is rejected.
- An existing silent audio stream at 1x renders successfully and yields 288000
  envelope samples; a missing audio stream is rejected as `NO_AUDIO` in the
  envelope path. Silence is not treated as a missing track.
- A nonexistent audio stream index is rejected by text comparison as
  `AUDIO_STREAM_REQUIRED`; this is safe rejection, not a precise missing-index
  diagnostic.
- Audio-bearing 0.5x / 2x renders were **blocked**, not passed, because the pinned
  Rubber Band helper was absent. No alternative algorithm was substituted and
  no helper was installed. A real listen-through and the pinned-backend test
  remain outstanding.

These findings concern that exact baseline and synthetic media, not deployed
product health or human acceptance. No unrelated speed/audio patch was made.

For a newly created recipe whose only mapping is `line_breaks`, ordinary local
undo would leave an empty recipe. The default remains explicit rejection.
After selecting the exact original edit, callers can additionally set
`binding_resolution.detach_empty_binding: true` in the normal undo preparation
request. This only detaches the sole `*` style binding when the restored recipe
has **no** remaining mappings; nonempty mappings, mismatched hashes, changed
caption identity and failed current/restored layout checks still block it.
Undo preparation is not a commit. Inspect its candidate and explicitly commit
it using the existing current-version checks. No artificial color/font mapping
is added merely to make undo pass.
