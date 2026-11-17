"""Pure, offline HTML presentation of film-revision-preview/1; no I/O."""
from html import escape


_LABELS = {
    "rankings": "检索排名声明", "exclusions": "排除记录", "budget_exclusions": "预算排除记录",
    "units": "素材单元", "character_focus": "人物关注声明", "event_ids": "事件引用 ID",
    "change": "情节变化声明", "direct_unit_ids": "直接举证单元声明",
    "pool_unit_ids": "候选池单元 ID", "in_event_span": "位于事件区间的声明",
    "role": "用途声明", "selected": "选择标记", "limitation": "限制说明",
    "status": "状态", "reason": "原因 / 失效说明", "source_id": "源素材 ID",
    "path": "记录路径（不加载文件）", "sha256": "SHA-256", "bytes": "字节数",
    "start": "源片入点（秒）", "end": "源片出点（秒）", "unit_id": "素材单元 ID",
    "segment_id": "片段 ID", "beat_id": "Beat ID", "visual_role": "画面用途声明",
    "beat_role": "本 Beat 的用途声明", "entered_candidate_pool": "记录为进入候选池",
    "location": "位置", "protected": "保护标记", "changed_segment_ids": "检测到变化的片段",
    "fields": "申请修改字段", "segment_ids": "申请修改片段", "generation": "基线版本目录",
    "state_sha256": "基线状态哈希", "pointer_sha256": "版本指针哈希",
    "media_reverified": "本次重新验证媒体", "qc_inherited": "继承旧 QC",
    "support_complete": "叙事支持是否完整", "method": "检索方法", "coverage": "覆盖声明",
    "plan_binding": "方案引用状态", "asset_bytes_verified": "素材字节已核验",
    "coverage_status": "覆盖状态", "requested_range": "申请源片区间",
    "target_sha256": "片段内容哈希", "highlight_id": "高光 ID",
}
_STATUS = {"unknown": "未知 / unknown", "recorded": "已有记录 / recorded",
           "not_validated": "未验证 / not_validated", "rejected": "拒绝 / rejected",
           "not_requested": "未请求 / not_requested",
           "within_existing_local_scope": "处于现有局部范围（仅部分检查） / within_existing_local_scope",
           "not_applicable": "不适用 / not_applicable",
           "recorded_reference": "已有方案引用 / recorded_reference",
           "missing_beat": "缺少方案 Beat / missing_beat",
           "candidate_evidence": "候选证据声明，未验证完整支持 / candidate_evidence",
           "realized_timeline_missing": "没有实际成片时间线记录 / realized_timeline_missing",
           "candidate_has_not_been_rendered": "该候选尚未渲染 / candidate_has_not_been_rendered",
           "existing_render_plan_content_binding": "已有渲染计划内容绑定，非新验收 / existing_render_plan_content_binding",
           "recorded_pool_ids": "已有候选池成员记录 / recorded_pool_ids",
           "pool_membership_not_recorded": "候选池成员未记录 / pool_membership_not_recorded",
           "beat_coverage_not_recorded": "Beat 覆盖未记录 / beat_coverage_not_recorded",
           "no_recorded_r1_beat_evidence": "缺少该 Beat 的 R1 检索记录 / no_recorded_r1_beat_evidence",
           "knowledge_constraint": "知识范围限制 / knowledge_constraint",
           "writer_budget": "文案选材预算限制 / writer_budget",
           "direct": "直接举证用途声明 / direct", "context_only": "仅上下文用途声明 / context_only",
           "direct_evidence": "直接举证用途声明 / direct_evidence", "context": "上下文用途声明 / context"}
for _code, _description in {
    "render_storyboard_source_binding_mismatch": "成片与分镜源身份不匹配",
    "render_evidence_not_bound": "成片证据未绑定",
    "render_artifact_binding_mismatch": "成片产物绑定不匹配",
    "render_plan_storyboard_binding_mismatch": "渲染计划与分镜绑定不匹配",
    "render_voice_binding_mismatch": "配音绑定不匹配",
    "render_edl_storyboard_binding_mismatch": "EDL 与分镜绑定不匹配",
    "render_evidence_unusable": "成片证据不可用",
}.items():
    _STATUS[_code] = _description + " / " + _code
_LABELS.update({
    "support_windows_sha256": "支持窗口声明 SHA-256（非语义金标）",
    "declaration": "输入窗口与依据声明", "alternatives": "替代支持组（任一组满足记录要求）",
    "windows": "同组必需窗口（全部满足记录要求）", "covered": "已记录覆盖区间（源秒）",
    "gaps": "记录未覆盖区间（源秒；未知时不等于实际缺失）",
    "mapping_unknowns": "区间映射未知原因", "basis": "人工 / 上游声明依据",
    "source_sha256": "声明源 SHA-256", "render_binding_status": "已有成片记录绑定状态",
    "render_binding_reason": "已有成片记录绑定限制", "declaration_is_semantic_gold": "声明是否语义金标",
    "physical_frame_coverage": "逐帧实际消费验证", "semantic_review": "语义验收",
    "num": "分子", "den": "分母",
})
_STATUS.update({
    "RECORDED_WINDOW_FULL": "记录窗口完整覆盖（不等于逐帧消费或语义支持） / RECORDED_WINDOW_FULL",
    "RECORDED_WINDOW_PARTIAL": "记录窗口部分覆盖 / RECORDED_WINDOW_PARTIAL",
    "RECORDED_WINDOW_MISSING": "记录窗口未覆盖（不等于已证实实际缺失） / RECORDED_WINDOW_MISSING",
    "UNKNOWN": "记录窗口覆盖未知 / UNKNOWN",
    "NOT_VERIFIED": "未验证 / NOT_VERIFIED", "NOT_RUN": "未执行 / NOT_RUN",
})
for _code, _description in {
    "unsupported_nonoriginal_or_multivisual": "非原声模式或多画面映射不在本次诊断支持范围",
    "segment_contract_missing": "缺少唯一片段或合成合同",
    "segment_contract_key_mismatch": "片段与合成依赖键不匹配",
    "millisecond_seek_rounding_unresolved": "毫秒寻址取整关系未解决",
    "segment_source_binding_mismatch": "片段源字节身份绑定不匹配",
    "segment_source_window_mismatch": "片段源窗口记录不匹配",
    "realized_segment_missing": "缺少唯一实际时间线片段记录",
    "measured_duration_not_exact_source_window": "测得时长不能精确映射到源窗口",
    "edl_duration_not_exact_source_window": "EDL时长不能精确映射到源窗口",
    "segment_contract_unusable": "片段合同记录不可用",
    "edl_segment_missing": "缺少唯一EDL片段记录",
}.items():
    _STATUS[_code] = _description + " / " + _code
_CODE_FIELDS = {"status", "reason", "plan_binding", "coverage_status", "beat_role", "visual_role", "role", "render_binding_status", "render_binding_reason", "physical_frame_coverage", "semantic_review"}


def _text(value):
    if value is None:
        return "未提供 / unknown"
    if isinstance(value, bool):
        return "是" if value else "否"
    return escape(str(value), quote=True)


def _value(value, field=None, interpret=True):
    """Render every supplied field, including unfamiliar declarations, as escaped text."""
    if isinstance(value, dict):
        return "<dl>" + "".join(
            f"<dt>{_text(_LABELS.get(k, k) if interpret else k)}</dt><dd>{_value(v, k, interpret and k != 'unknown_fields')}</dd>" for k, v in value.items()
        ) + "</dl>" if value else '<p class="muted">无记录</p>'
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_value(v, interpret=interpret)}</li>" for v in value) + "</ul>" if value else '<p class="muted">无记录</p>'
    if interpret and field in _CODE_FIELDS and isinstance(value, str):
        value = _STATUS.get(value, "未解释的记录代码 / " + value)
    return f'<span class="value">{_text(value)}</span>'


def _details(title, value):
    return f"<details><summary>{escape(title)}</summary>{_value(value)}</details>"


def _retrieval(value):
    large = {"rankings", "exclusions", "budget_exclusions"}
    result = _value({k: v for k, v in value.items() if k not in large})
    for key in ("rankings", "exclusions", "budget_exclusions"):
        rows = value.get(key, [])
        summary = f"{len(rows)} 条" if isinstance(rows, list) else "格式异常，非列表"
        result += _details(f"{_LABELS[key]}：{summary}（展开查看原记录）", rows)
    return result


def render_preview_html(preview):
    """Present an already computed preview, never read files or update workspace state."""
    if preview.get("schema") != "film-revision-preview/1":
        raise ValueError("UNSUPPORTED_PREVIEW_REPORT_SCHEMA")
    # A report must never turn an unrelated/modified input into an apparent QC pass.
    if preview.get("qc_status") != "NOT_RUN" or preview.get("semantic_and_av_review_inherited") is not False:
        raise ValueError("PREVIEW_REPORT_REQUIRES_NOT_RUN")
    candidate = preview.get("binding", {}).get("proposal_sha256") is not None
    mode = "候选修改预览 · 尚未采用" if candidate else "当前分镜记录预览"
    beats = preview.get("beats", [])
    navigation = '<nav aria-label="Beat 目录"><ul>' + "".join(
        f'<li><a href="#beat-{i}">{_text(beat.get("beat_id"))}</a></li>' for i, beat in enumerate(beats)
    ) + '</ul></nav>'
    summary = f'<p>源素材 {len(preview.get("base", {}).get("sources", []))} 个 · Beat {len(beats)} 个 · {_text(mode)} · 未验收</p>'
    body = [f'<header><p>Reel Scribe · 只读证据报告</p><h1>{mode}</h1>',
            summary, navigation, '<p class="notice">QC：NOT_RUN。本报告没有执行语义、音画或真实用户验收，不继承旧 QC。</p>',
            '<p>候选池 ≠ 分镜引用 ≠ 成片消费。以下是已有记录与创作声明，不自动认证为事实；缺项保持未知。</p>',
            '<p>离线快照只对应下列基线；打开本页不会复核后来发生的变化。采用修改前需重新检查基线与执行原验证。</p></header>',
            '<main><section><h2>1. 基线与源素材身份</h2>']
    base = preview.get("base", {})
    body += [_value({"generation": base.get("generation")}), _value(base.get("sources", [])),
             _details("基线哈希、音频与文档绑定", {"base": base, "binding": preview.get("binding")}), '</section>',
             '<section><h2>2. 修改范围与保护</h2>', _value(preview.get("scope_check")),
             _value({"申请范围": preview.get("scope"), "采用状态": preview.get("adoption", {}).get("status", "unknown")}),
             '<p>这里只列检测到变化的片段 ID，不是逐字段前后差异。范围检查不等于采用通过；片段保护标记见下方分镜。</p>',
             _details("采用限制与专用命令（不会执行）", preview.get("adoption")), '</section>',
             '<section><h2>3. 选材候选记录</h2>', _value(preview.get("candidate_pool")),
             _details("高光候选声明（不代表已采用）", preview.get("highlights", [])), '</section>',
             '<section><h2>4. 按 Beat 定位</h2>']
    diagnostics = preview.get("support_window_diagnostics")
    if "support_window_diagnostics" in preview:
        body += ['<aside class="support-windows"><h3>可选：支持窗口记录诊断</h3>',
                 '<p class="notice">这里只比对声明窗口与已绑定的成片记录。FULL 不是逐帧消费、叙事支持或语义真值；PARTIAL / MISSING 不是自动发布阻断，UNKNOWN 必须连同原因阅读。</p>',
                 '<p>组内窗口为全部需要，替代组为任一可满足。区间使用精确分数表示源秒。声明依据不是金标；不改变原采用流程或 QC 门槛。</p>']
        if isinstance(diagnostics, dict):
            body += [_value({k:v for k,v in diagnostics.items() if k not in {"beats", "declaration"}}),
                     _details("原始支持窗口与依据声明（不认证为事实）", diagnostics.get("declaration")),
                     _details("全部 Beat 窗口诊断原记录", diagnostics.get("beats"))]
        else:
            body += ['<p class="muted">诊断格式异常，未解释为覆盖结论。</p>', _value(diagnostics)]
        body += ['</aside>']
    body += [navigation]
    if not beats:
        body += ['<p class="muted">无 Beat 记录；不能由此推断作品完整。</p>']
    for i, beat in enumerate(beats):
        body += [f'<article id="beat-{i}"><h3>Beat：{_text(beat.get("beat_id"))}</h3>',
                 '<h4>方案声明</h4>', _value({"plan_binding": beat.get("plan_binding")}), _value(beat.get("plan")),
                 '<h4>检索与未知项</h4>', _retrieval(beat.get("retrieval", {})), '<h4>分镜引用（不是成片证明）</h4>']
        if "support_window_diagnostics" in preview:
            entries = diagnostics.get("beats") if isinstance(diagnostics, dict) else None
            matches = [row for row in entries if isinstance(row, dict) and row.get("beat_id") == beat.get("beat_id")] if isinstance(entries, list) else []
            body += ['<h4>本 Beat 的声明窗口记录覆盖</h4>']
            if len(matches) == 1:
                body += [_value(matches[0])]
            elif not matches:
                body += ['<p class="muted">本 Beat 没有可对应的窗口诊断；不推断完整或缺失。</p>']
            else:
                body += ['<p class="muted">出现重复 Beat 诊断，未合并为单一结论。</p>', _value(matches)]
        references = beat.get("storyboard_references", [])
        if not references:
            body += ['<p class="muted">无分镜引用记录</p>']
        for ref in references:
            body += [f'<div class="segment"><h5>片段 {_text(ref.get("segment_id"))} · {_text(ref.get("title"))}</h5>',
                     _value({"模式": ref.get("mode"), "protected": ref.get("protected"),
                             "文案声明": ref.get("text"), "备注声明": ref.get("notes"), "highlight_id": ref.get("highlight_id")}),
                     '<h6>源片区间与用途声明</h6>', _value(ref.get("visuals", [])),
                     _details("片段内容哈希与未解释字段", {"target_sha256": ref.get("target_sha256"), "unknown_fields": ref.get("unknown_fields")}), '</div>']
        body += ['<h4>成片消费记录</h4><p>记录绑定不等于本次重新解码或质量验收；候选不得沿用当前成片证明。</p>',
                 _value(beat.get("render_consumption")),
                 _details("区间重叠的原始证据卡 ID（重叠不证明支持）", beat.get("overlapping_raw_card_ids", [])), '</article>']
    body += ['</section><section><h2>5. 原始证据卡声明</h2><p>保留提供者的证据类型与原文；不自动确认素材字节、内容真实性或完整叙事支持。</p>',
             _value(preview.get("raw_evidence", [])), '</section><section><h2>6. 未执行与限制</h2>',
             '<p>本次未采用修改，未渲染，未调用模型或服务，未提取原始素材。QC：NOT_RUN。</p>',
             _value(preview.get("limitations", [])), '</section></main>']
    style = """body{margin:0;background:#f6f7f9;color:#172536;font:16px/1.65 system-ui,sans-serif}header,main{max-width:1060px;margin:auto;padding:24px}h1{font-size:1.8rem}h2{font-size:1.35rem}h3{font-size:1.2rem}h4,h5,h6{font-size:1rem;margin:16px 0 8px}section,article,.segment{background:white;border:1px solid #d6dfe8;border-radius:10px;padding:20px;margin:18px 0}article{border-left:5px solid #356a94}.notice{background:#fff3cc;padding:14px;border-radius:8px;font-weight:600}.muted{color:#526273}dl{display:grid;grid-template-columns:minmax(9em,25%) minmax(0,1fr);gap:6px 16px}dt{font-weight:600}dd{margin:0;min-width:0}li{margin:8px 0}dd dl{display:block}dd dt{margin-top:8px}.value,dt,h1,h3,h5,a{white-space:pre-wrap;overflow-wrap:anywhere}details{margin:14px 0}summary{cursor:pointer;color:#245d88}a{color:#245d88}nav ul{display:flex;flex-wrap:wrap;gap:12px 24px}@media(max-width:600px){header,main{padding:12px}section,article,.segment{padding:12px}dl{display:block}dt{margin-top:10px}}@media print{body{background:white}header,main{max-width:none}section,article{break-inside:avoid}a{color:inherit}}"""
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<title>Reel Scribe · 只读证据报告</title><style>' + style + '</style></head><body>' + ''.join(body) + '</body></html>')
