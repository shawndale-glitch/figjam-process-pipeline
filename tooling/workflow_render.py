"""Render the human process page and the conformance scenarios from workflow.yaml.

Usage:
  python tooling/workflow_render.py workflows/<area>/<ID>/workflow.yaml
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workflow_core import FLOW_TYPES, deep_link, paths  # noqa: E402

REPO_URL = "https://github.com/shawndale-glitch/figjam-process-pipeline/blob/main"
GEN_START = "<!-- generated:start (tooling/workflow_render.py; edit the FigJam board, not this block) -->"
GEN_END = "<!-- generated:end -->"


def _mid(i: str) -> str:
    return "n" + i.replace(":", "_")


def _shape(n: dict) -> str:
    t = n["label"].replace('"', "'") or "(no label)"
    return {
        "event.start": f'(("{t}"))', "event.end": f'((("{t}")))', "event.intermediate": f'(("{t}"))',
        "gateway.xor": f'{{"{t}"}}', "gateway.and": '{"+"}', "task": f'["{t}"]', "subprocess": f'[["{t}"]]',
        "system": f'[("{t}")]', "datastore": f'[("{t}")]', "document": f'[/"{t}"/]', "rule": f'>"{t}"]', "link": f'(("{t}"))',
    }.get(n["type"], f'["{t}"]')


def mermaid(wf: dict) -> str:
    L = ["```mermaid", "flowchart LR"]
    for lane in wf["lanes"]:
        L.append(f'  subgraph {_mid(lane["id"])}["{lane["role"]}"]')
        for n in wf["nodes"]:
            if n.get("lane") == lane["role"]:
                L.append(f"    {_mid(n['id'])}{_shape(n)}")
        L.append("  end")
    for n in wf["nodes"]:
        if not n.get("lane"):
            L.append(f"  {_mid(n['id'])}{_shape(n)}")
    for f in wf["flows"]:
        arrow = "-.->" if f["type"] == "message" else "-->"
        cond = f"|{f['condition']}|" if f.get("condition") else ""
        L.append(f"  {_mid(f['from'])} {arrow}{cond} {_mid(f['to'])}")
    for a in wf.get("associations", []):
        L.append(f"  {_mid(a['from'])} -.- {_mid(a['to'])}")
    L.append("```")
    return "\n".join(L)


def page(wf: dict) -> str:
    p = wf["process"]
    key = p["source"]["figma_file_key"]
    by_id = {n["id"]: n for n in wf["nodes"]}
    out_ = {n["id"]: [f for f in wf["flows"] if f["from"] == n["id"]] for n in wf["nodes"]}
    rel = f"workflows/{p['area']}/{p['id']}"
    L = [f"# {p['id']}: {p['name']}", ""]
    if p["status"] != "validated":
        L += ['!!! warning "DRAFT"', f"    Status `{p['status']}`. This process has not been validated by a business SME. Do not build against it.", ""]
    L += [GEN_START, "",
          "| | |", "|---|---|",
          f"| Process ID | `{p['id']}` |",
          f"| Version | `{p['version']}` |",
          f"| Status | {p['status']} |",
          f"| Owner | {p['owner']} |",
          f"| State | {p['state']} |",
          f"| Last updated | {p['updated']} |",
          f"| Source | [FigJam section]({deep_link(key, p['source']['figma_page_or_section'])}) |",
          f"| Machine-readable | [`workflow.yaml`]({REPO_URL}/{rel}/workflow.yaml) · [changelog]({REPO_URL}/{rel}/CHANGELOG.md) · [scenarios]({REPO_URL}/conformance/{p['id']}/scenarios.feature) |",
          "", "## Flow", "", mermaid(wf), "", "## Steps", "",
          "| Step | Lane | Type | Label | Next |", "|---|---|---|---|---|"]
    for n in wf["nodes"]:
        if n["type"] not in FLOW_TYPES:
            continue
        nxt = "; ".join((f"**{f['condition']}** → " if f.get("condition") else "") + by_id[f["to"]]["label"] for f in out_[n["id"]]) or "—"
        L.append(f"| [`{n['id']}`]({deep_link(key, n['id'])}) | {n.get('lane') or '—'} | {n['type']} | {n['label']} | {nxt} |")
    rules = [n for n in wf["nodes"] if n["type"] == "rule"]
    if rules:
        L += ["", "## Business rules", "", "| Rule | Applies to |", "|---|---|"]
        for r in rules:
            tgt = [a["to"] if a["from"] == r["id"] else a["from"] for a in wf.get("associations", []) if r["id"] in (a["from"], a["to"])]
            L.append(f"| {r['label']} | {', '.join(by_id[t]['label'] for t in tgt) or '—'} |")
    data = [n for n in wf["nodes"] if n["type"] in ("system", "document", "datastore")]
    if data:
        L += ["", "## Systems and data", ""] + [f"- [{d['label']}]({d['url']}) ({d['type']})" if d.get("url") else f"- {d['label']} ({d['type']})" for d in data]
    if wf.get("notes"):
        L += ["", "## Notes from the board", ""] + [f"- {x['text']} ({x.get('author') or 'unknown'})" for x in wf["notes"]]
    L += ["", "## Conformance", "", "| Consumer | Version | C1 | C2 | C3 | C4 |", "|---|---|---|---|---|---|",
          "| — | — | not verified | not verified | not verified | not verified |", "", GEN_END, ""]
    return "\n".join(L)


# ---------------------------------------------------------------- scenarios

def paths_through(wf: dict) -> list[list[tuple[str, str | None]]]:
    """All simple start-to-end paths as [(node_id, condition_taken_to_get_here)]."""
    out_ = {}
    for f in wf["flows"]:
        if f["type"] in ("sequence", "message"):  # a handoff continues the path
            out_.setdefault(f["from"], []).append(f)
    by = {n["id"]: n for n in wf["nodes"]}
    start = next(n["id"] for n in wf["nodes"] if n["type"] == "event.start")
    res = []

    def walk(nid, trail, seen):
        if by[nid]["type"] == "event.end":
            res.append(trail)
            return
        for f in out_.get(nid, []):
            if f["to"] not in seen:
                walk(f["to"], trail + [(f["to"], f.get("condition"))], seen | {f["to"]})

    walk(start, [(start, None)], {start})
    return sorted(res, key=len)


def scenarios(wf: dict) -> str:
    p = wf["process"]
    by = {n["id"]: n for n in wf["nodes"]}
    L = [f"# Generated from workflows/{p['area']}/{p['id']}/workflow.yaml by tooling/workflow_render.py. Do not edit.",
         "# Happy path = the shortest start-to-end path (governance/workflow-rules.yaml, conformance C2).",
         f"@{p['id']} @v{p['version']}",
         f"Feature: {p['id']} {p['name']}", ""]
    for i, path in enumerate(paths_through(wf), 1):
        tags = "@happy " if i == 1 else ""
        conds = [c for _, c in path if c]
        L.append(f"  {tags}@path-{i}")
        L.append(f"  Scenario: Path {i}" + (f" ({', '.join(conds)})" if conds else ""))
        first = True
        pending_cond = None
        for nid, cond in path:
            n = by[nid]
            if cond:
                L.append(f'    And the decision resolves to "{cond}"')
            if n["type"] == "event.start":
                L.append(f'    Given the process "{p["id"]}" starts with "{n["label"]}" [{nid}]')
            elif n["type"] == "event.end":
                L.append(f'    Then the process ends with "{n["label"]}" [{nid}]')
            elif n["type"] == "gateway.xor":
                L.append(f'    And "{n["lane"]}" decides "{n["label"]}" [{nid}]')
            else:
                kw = "When" if first else "And"
                first = False
                L.append(f'    {kw} "{n["lane"]}" performs "{n["label"]}" [{nid}]')
        L.append("")
    return "\n".join(L)


def main(path: str) -> None:
    wf = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    pth = paths(wf)
    pth["page"].parent.mkdir(parents=True, exist_ok=True)
    pth["page"].write_text(page(wf), encoding="utf-8")
    pth["scenarios"].parent.mkdir(parents=True, exist_ok=True)
    pth["scenarios"].write_text(scenarios(wf), encoding="utf-8")
    print(f"wrote {pth['page'].relative_to(pth['page'].parents[3])} and {pth['scenarios'].name}")


if __name__ == "__main__":
    main(sys.argv[1])
