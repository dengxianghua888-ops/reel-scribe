#!/usr/bin/env python3
"""Build and check the multi-style catalog (design stage).

Checks: every pack references an existing method card and existing facets; cost tier is derived
from engines and services; packs inside one scenario stay distinguishable (similarity < 0.85, the
03-style-routing definition); every scenario has at least 6 packs. Emits catalog/*.json and *.md.
Does not render, route or judge quality.
"""
import itertools
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalog_facets as F  # noqa: E402
import catalog_packs as K  # noqa: E402
import survey_sources as S  # noqa: E402

DOC = HERE.parent
REPO = DOC.parents[1]
OUT = DOC / "catalog"
AXES = ("tempo", "density", "ornament", "warmth", "contrast", "formality", "motion")
MOTION_BY_CATEGORY = {"text": 0.6, "caption": 0.6, "camera": 0.6, "transition": 0.6, "sticker": 0.7, "av": 0.7, "light": 0.6,
                      "card": 0.35, "data": 0.35, "annotate": 0.35, "diagram": 0.35, "screen": 0.35,
                      "composite": 0.3, "track": 0.3, "stylize": 0.3, "background": 0.3}
SIM_LIMIT = 0.85
MIN_PACKS = 6


def method_cards():
    cards = {}
    for path in sorted((REPO / "styles").glob("*/catalog.json")):
        for style in json.loads(path.read_text(encoding="utf-8"))["styles"]:
            cards[f"{path.parent.name}/{style['id']}"] = style["name"]
    return cards


def vector(pack):
    _, _, _, rhythm, ds, caption, look, sound, comps, _ = pack
    family = F.DESIGN_SYSTEMS[ds][1]
    _, ornament, formality = F.FAMILIES[family]
    cap_motion = F.CAPTIONS[caption][5]
    comp_motion = [MOTION_BY_CATEGORY[F.COMPONENTS[c][1]] for c in comps]
    motion = 0.5 * cap_motion + 0.5 * (sum(comp_motion) / len(comp_motion) if comp_motion else 0.0)
    density = min(1.0, 0.12 * len(comps) + 0.3 * F.SOUNDS[sound][1] + (0.2 if cap_motion > 0.5 else 0.0))
    return {"tempo": F.RHYTHMS[rhythm][1], "density": round(density, 3), "ornament": ornament,
            "warmth": F.LOOKS[look][1], "contrast": F.LOOKS[look][2], "formality": formality, "motion": round(motion, 3)}


def similarity(a, b):
    va, vb = a["vector"], b["vector"]
    dist = math.sqrt(sum((va[k] - vb[k]) ** 2 for k in AXES))
    share = sum(a["facets"][k] == b["facets"][k] for k in ("method", "design_system", "caption_style", "sound")) / 4
    return 0.6 * (1 - dist / math.sqrt(len(AXES))) + 0.4 * share


def engines_of(pack):
    _, _, _, _, _, caption, look, _, comps, _ = pack
    impl = F.CAPTION_IMPL.get(caption, [])
    used = {F.COMPONENTS[c][2] for c in comps + impl} | {F.CAPTIONS[caption][4]}
    return used


def build():
    errors, warnings = [], []
    cards = method_cards()
    packs, ids = [], set()
    for sid, items in K.P.items():
        if sid not in K.SCENARIOS:
            errors.append(f"unknown scenario {sid}")
            continue
        scen = K.SCENARIOS[sid]
        if len(items) < MIN_PACKS:
            errors.append(f"{sid} has {len(items)} packs (< {MIN_PACKS})")
        for pack in items:
            pid, name, method, rhythm, ds, caption, look, sound, comps, signature = pack
            if pid in ids:
                errors.append(f"duplicate pack id {pid}")
            ids.add(pid)
            refs = [(method, cards, "method card"), (rhythm, F.RHYTHMS, "rhythm"), (ds, F.DESIGN_SYSTEMS, "design system"),
                    (caption, F.CAPTIONS, "caption style"), (look, F.LOOKS, "look"), (sound, F.SOUNDS, "sound")]
            refs += [(c, F.COMPONENTS, "component") for c in comps]
            missing = [f"{kind} {ref}" for ref, table, kind in refs if ref not in table]
            missing += [f"caption impl {c}" for c in F.CAPTION_IMPL.get(caption, []) if c not in F.COMPONENTS]
            if missing:
                errors.append(f"{pid}: missing {', '.join(missing)}")
                continue
            eng = engines_of(pack)
            services = set(scen[5]) | set(K.SERVICE_REQUIREMENTS.get(pid, []))
            mechanism = bool(eng & F.MECHANISM_ENGINES) or F.LOOKS[look][4] or bool(services)
            tier_reasons = sorted(eng & F.MECHANISM_ENGINES) + (["look:" + look] if F.LOOKS[look][4] else []) + sorted("service:" + s for s in services)
            packs.append({
                "id": pid, "name": name, "scenario": sid, "scenario_name": scen[0], "workflow": scen[2],
                "route": "HYBRID" if services else "EDIT",
                "cost_tier": "mechanism" if mechanism else "skin", "tier_reasons": tier_reasons,
                "facets": {"method": method, "rhythm": rhythm, "design_system": ds, "caption_style": caption,
                           "look": look, "sound": sound, "components": comps},
                "method_card_name": cards[method], "engines": sorted(eng), "signature": signature,
                "vector": vector(pack), "status": "catalog-draft",
            })
    by_scen = defaultdict(list)
    for p in packs:
        by_scen[p["scenario"]].append(p)
    max_sim = {}
    for sid, group in by_scen.items():
        worst = 0.0
        for a, b in itertools.combinations(group, 2):
            s = similarity(a, b)
            worst = max(worst, s)
            if s >= SIM_LIMIT:
                errors.append(f"{sid}: {a['id']} ~ {b['id']} similarity {s:.3f} >= {SIM_LIMIT}")
        max_sim[sid] = round(worst, 3)
    sig = Counter((p["facets"]["method"], p["facets"]["design_system"], p["facets"]["caption_style"], p["facets"]["look"], p["facets"]["sound"]) for p in packs)
    for key, n in sig.items():
        if n > 1:
            warnings.append(f"identical facet combination used {n} times: {key}")
    usage = {kind: Counter() for kind in ("design_system", "caption_style", "look", "sound", "rhythm", "components")}
    for p in packs:
        for kind in ("design_system", "caption_style", "look", "sound", "rhythm"):
            usage[kind][p["facets"][kind]] += 1
        usage["components"].update(p["facets"]["components"] + F.CAPTION_IMPL.get(p["facets"]["caption_style"], []))
    unused = {
        "design_systems": sorted(set(F.DESIGN_SYSTEMS) - set(usage["design_system"])),
        "caption_styles": sorted(set(F.CAPTIONS) - set(usage["caption_style"]) - {"cap-baseline-plain"}),
        "looks": sorted(set(F.LOOKS) - set(usage["look"])),
        "sounds": sorted(set(F.SOUNDS) - set(usage["sound"])),
        "rhythms": sorted(set(F.RHYTHMS) - set(usage["rhythm"])),
        "components": sorted(set(F.COMPONENTS) - set(usage["components"])),
    }
    coverage = {
        "scenarios": len(by_scen), "packs": len(packs),
        "skin_packs": sum(p["cost_tier"] == "skin" for p in packs),
        "mechanism_packs": sum(p["cost_tier"] == "mechanism" for p in packs),
        "packs_per_scenario": {sid: len(g) for sid, g in sorted(by_scen.items())},
        "max_within_scenario_similarity": max_sim,
        "method_cards_used": len({p["facets"]["method"] for p in packs}), "method_cards_available": len(cards),
        "design_families_used": dict(Counter(F.DESIGN_SYSTEMS[p["facets"]["design_system"]][1] for p in packs)),
        "engines_used": dict(Counter(e for p in packs for e in p["engines"])),
        "facet_library": {"engines": len(F.ENGINES), "components": len(F.COMPONENTS), "design_systems": len(F.DESIGN_SYSTEMS),
                          "design_families": len(F.FAMILIES), "caption_styles": len(F.CAPTIONS), "looks": len(F.LOOKS),
                          "sounds": len(F.SOUNDS), "rhythms": len(F.RHYTHMS)},
        "unused": unused,
    }
    return packs, coverage, errors, warnings


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def emit(packs, coverage):
    OUT.mkdir(exist_ok=True)
    note = "catalog-draft：结构化设计条目，未渲染、未评测；数量不代表已验证风格。"
    facets = {
        "engines": {k: dict(zip(("name", "best_for", "strengths", "limits", "determinism", "license_note"), v)) for k, v in F.ENGINES.items()},
        "component_categories": F.CATEGORIES,
        "components": {k: {"name": v[0], "category": v[1], "primary_engine": v[2], "fallback_engine": v[3], "editable_props": v[4].split(",")} for k, v in F.COMPONENTS.items()},
        "design_families": {k: {"name": v[0], "ornament": v[1], "formality": v[2]} for k, v in F.FAMILIES.items()},
        "design_systems": {k: dict(zip(("name", "family", "bg", "ink", "accent", "fonts", "motion"), v)) for k, v in F.DESIGN_SYSTEMS.items()},
        "caption_styles": {k: dict(zip(("name", "grouping", "emphasis", "animation", "engine", "motion", "note"), v)) for k, v in F.CAPTIONS.items()},
        "looks": {k: dict(zip(("name", "warmth", "contrast", "implementation", "mechanism", "note"), v)) for k, v in F.LOOKS.items()},
        "sounds": {k: dict(zip(("name", "density", "description"), v)) for k, v in F.SOUNDS.items()},
        "rhythms": {k: dict(zip(("name", "tempo", "description"), v)) for k, v in F.RHYTHMS.items()},
    }
    scenarios = {k: dict(zip(("name", "domain", "workflow", "material_start", "key_signals", "requires"), v)) for k, v in K.SCENARIOS.items()}
    dump = lambda name, obj: (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    dump("packs.json", {"schema": "style-pack-catalog/1", "status_note": note, "packs": packs})
    dump("scenarios.json", {"schema": "scenario-catalog/1", "scenarios": scenarios})
    dump("facets.json", {"schema": "facet-library/1", "status_note": note, **facets})
    dump("coverage.json", coverage)

    ds, cap, lk, sd = F.DESIGN_SYSTEMS, F.CAPTIONS, F.LOOKS, F.SOUNDS
    lines = ["# 场景 × 风格包目录", "", note, "",
             f"共 {coverage['scenarios']} 个场景、{coverage['packs']} 个风格包（皮肤包 {coverage['skin_packs']}、机制包 {coverage['mechanism_packs']}），"
             f"引用 {coverage['method_cards_used']} 张现有方法卡。生成方式：`python3 docs/multi-style/tools/build_catalog.py`。", ""]
    domain = None
    for sid, sc in K.SCENARIOS.items():
        if sc[1] != domain:
            domain = sc[1]
            lines += [f"## {domain}", ""]
        lines += [f"### {sid} {sc[0]}", "", f"工作流 `{sc[2]}` · 素材起点：{sc[3]} · 关键信号：{sc[4]}", ""]
        rows = []
        for p in [x for x in packs if x["scenario"] == sid]:
            f = p["facets"]
            comps = "、".join(F.COMPONENTS[c][0] for c in f["components"]) or "—"
            rows.append([f"`{p['id']}` {p['name']}", f"{p['method_card_name']}（`{f['method']}`）", ds[f["design_system"]][0],
                         cap[f["caption_style"]][0], lk[f["look"]][0], sd[f["sound"]][0], comps, p["signature"],
                         "机制" if p["cost_tier"] == "mechanism" else "皮肤"])
        lines += [md_table(["风格包", "方法卡", "设计系统", "字幕", "影调", "声音", "组件", "签名手法", "成本"], rows), ""]
    (OUT / "packs.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# 动效组件与渲染引擎目录", "", note, "", "## 渲染引擎", "",
             md_table(["ID", "引擎", "最适合", "强项", "局限", "确定性", "许可提示"], [[f"`{k}`", *v] for k, v in F.ENGINES.items()]), ""]
    used = Counter(c for p in packs for c in p["facets"]["components"] + F.CAPTION_IMPL.get(p["facets"]["caption_style"], []))
    for cat, cname in F.CATEGORIES.items():
        rows = [[f"`{k}`", v[0], f"`{v[2]}`", f"`{v[3]}`" if v[3] else "—", v[4].replace(",", "、"), used.get(k, 0)]
                for k, v in F.COMPONENTS.items() if v[1] == cat]
        lines += [f"## {cname}（{len(rows)}）", "", md_table(["ID", "组件", "首选引擎", "备选引擎", "可编辑属性", "被引用次数"], rows), ""]
    (OUT / "components.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# 设计系统、字幕、影调、声音与节奏库", "", note, "", "## 设计系统（按视觉语言分族）", ""]
    for fam, (fname, orn, formal) in F.FAMILIES.items():
        rows = [[f"`{k}`", v[0], f"`#{v[2]}` / `#{v[3]}` / `#{v[4]}`", v[5], v[6]] for k, v in ds.items() if v[1] == fam]
        lines += [f"### {fname}", "", md_table(["ID", "名称", "底 / 字 / 强调", "字体（许可待逐一核对）", "运动性格"], rows), ""]
    lines += ["## 字幕样式", "", md_table(["ID", "名称", "分组", "强调", "动画", "引擎", "说明"],
                                         [[f"`{k}`", v[0], v[1], v[2], v[3], f"`{v[4]}`", v[6]] for k, v in cap.items()]), ""]
    lines += ["## 影调", "", md_table(["ID", "名称", "实现", "机制", "说明"],
                                    [[f"`{k}`", v[0], v[3], "是" if v[4] else "否", v[5]] for k, v in lk.items()]), ""]
    lines += ["## 声音", "", md_table(["ID", "名称", "说明"], [[f"`{k}`", v[0], v[2]] for k, v in sd.items()]), ""]
    lines += ["## 节奏", "", md_table(["ID", "名称", "说明"], [[f"`{k}`", v[0], v[2]] for k, v in F.RHYTHMS.items()]), ""]
    (OUT / "facet-libraries.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# 公开仓库调研表", "", "2026-11-26 调研；提交号由 `git ls-remote` 取当日 HEAD，许可读自仓库 LICENSE 文件。"
             "“仅非商业”与“无 LICENSE 文件”的条目只作效果与方法参照，不进入商用实现。", ""]
    for cat, cname in S.CATEGORIES.items():
        rows = []
        for c, repo, lic, shows, take, skip in S.SOURCES:
            if c != cat:
                continue
            sha = S.PINS[repo]
            rows.append([f"[{repo}](https://github.com/{repo}/tree/{sha})", f"`{sha[:12]}`", lic, shows, take, skip])
        lines += [f"## {cat} {cname}（{len(rows)}）", "", md_table(["仓库", "提交", "许可", "它提供什么", "我们借鉴", "不借鉴"], rows), ""]
    (OUT / "public-survey.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    dump("public-survey.json", {"schema": "public-survey/1", "date": "2026-11-26",
                                "sources": [dict(zip(("category", "repo", "license", "shows", "take", "skip"), x), commit=S.PINS[x[1]]) for x in S.SOURCES]})


def main():
    packs, coverage, errors, warnings = build()
    if not errors:
        emit(packs, coverage)
    summary = {k: coverage[k] for k in ("scenarios", "packs", "skin_packs", "mechanism_packs", "method_cards_used", "facet_library", "unused")}
    summary["worst_similarity"] = max(coverage["max_within_scenario_similarity"].values()) if coverage["max_within_scenario_similarity"] else None
    print(json.dumps({"status": "FAILED" if errors else "PASSED", **summary, "errors": errors, "warnings": warnings}, ensure_ascii=False, indent=1))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
