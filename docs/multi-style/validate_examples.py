#!/usr/bin/env python3
"""Validate the multi-style design examples against their draft schemas.

Design-stage helper only: it checks structure, pack inheritance rules and
pairwise style-vector similarity. It does not render, route or judge quality.
Requires `jsonschema` (not a runtime dependency of the library).
"""
import json
import math
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
SCHEMAS = {
    "material-profile/1": "material-profile.schema.json",
    "style-facet/1": "facets.schema.json",
    "style-pack/1": "style-pack.schema.json",
    "style-route-result/1": "style-route-result.schema.json",
    "style-plan/1": "style-plan.schema.json",
    "drama-post-handoff/1": "post-handoff.schema.json",
    "shot-request/1": "shot-request.schema.json",
}
SKIN_OVERRIDABLE = {"design_system", "caption_style", "look", "sound", "components", "method", "rhythm"}
AXES = ("tempo", "density", "ornament", "warmth", "contrast", "formality", "motion")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


SHARED_FACETS = ("method", "design_system", "caption_style", "sound")


def similarity(a, b):
    """05-style-routing §六: 0.6 * (1 - L2/sqrt(7)) + 0.4 * shared discrete facets."""
    va, vb = a["vector"], b["vector"]
    dist = math.sqrt(sum((va.get(k, 0.0) - vb.get(k, 0.0)) ** 2 for k in AXES))
    continuous = 1 - dist / math.sqrt(len(AXES))
    share = sum(a["facets"].get(k) == b["facets"].get(k) for k in SHARED_FACETS) / len(SHARED_FACETS)
    return 0.6 * continuous + 0.4 * share


def main():
    errors = []
    validators = {}
    for schema_id, name in SCHEMAS.items():
        schema = load(HERE / "schemas" / name)
        Draft202012Validator.check_schema(schema)
        validators[schema_id] = Draft202012Validator(schema)

    packs = {}
    for path in sorted((HERE / "examples").glob("*.json")):
        doc = load(path)
        validator = validators.get(doc.get("schema"))
        if validator is None:
            errors.append(f"{path.name}: unknown schema {doc.get('schema')}")
            continue
        for err in validator.iter_errors(doc):
            errors.append(f"{path.name}: {'/'.join(map(str, err.path))}: {err.message}")
        if doc["schema"] == "style-pack/1":
            packs[doc["id"]] = doc

    for pack in packs.values():
        base_ref = pack.get("extends")
        if not base_ref:
            continue
        base = packs.get(base_ref.split("@")[0])
        if base is None:
            errors.append(f"{pack['id']}: base {base_ref} not found")
            continue
        if pack["cost_tier"] == "skin":
            if "pipeline" in pack:
                errors.append(f"{pack['id']}: skin pack must not override pipeline")
            extra = set(pack["facets"]) - SKIN_OVERRIDABLE
            if extra:
                errors.append(f"{pack['id']}: skin pack overrides non-skin facets {sorted(extra)}")
            base_caps = set(base.get("capability_requirements", {}).get("required", []))
            own_caps = set(pack.get("capability_requirements", {}).get("required", []))
            if own_caps - base_caps:
                errors.append(f"{pack['id']}: skin pack adds required capabilities {sorted(own_caps - base_caps)}; use cost_tier=mechanism")

    skins = [p for p in packs.values() if p.get("cost_tier") == "skin" and "vector" in p]
    report = {}
    for i, a in enumerate(skins):
        for b in skins[i + 1:]:
            sim = round(similarity(a, b), 3)
            report[f"{a['id']}~{b['id']}"] = sim
            if a.get("extends") == b.get("extends") and sim >= 0.85:
                errors.append(f"{a['id']} and {b['id']}: style vectors too similar ({sim}) for sibling skins")

    print(json.dumps({"status": "FAILED" if errors else "PASSED", "examples": len(list((HERE / "examples").glob("*.json"))),
                      "packs": sorted(packs), "skin_similarity": report, "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
