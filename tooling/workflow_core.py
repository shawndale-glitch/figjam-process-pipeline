"""Shared logic for the FigJam -> repository workflow pipeline.

Rules live in governance/workflow-rules.yaml; the contract for the output is
schemas/workflow.schema.json. This module turns a board.json (from
tooling/figjam_extract.js) into a workflow dict, lints it, versions it, and renders
the human page and the conformance scenarios.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "1.0.0"

# Library component name -> workflow node type. Keyed on name for readability;
# COMPONENT_KEYS pins the published component keys so a renamed or translated
# component still maps to the same type.
# Library component name -> workflow node type, for the Spanish and English pages of
# "Process Design Standards/Components". COMPONENT_KEYS pins the published keys
# so a renamed component still maps to the same type; names are the fallback.
COMPONENT_TYPES = {
    # Español
    "Eventos/Evento de inicio": "event.start",
    "Eventos/Evento intermedio": "event.intermediate",
    "Eventos/Evento de fin": "event.end",
    "Eventos/Conector fuera de página": "link",
    "Actividades/Actividad": "task",
    "Actividades/Subproceso": "subprocess",
    "Compuertas/Decisión (XOR)": "gateway.xor",
    "Compuertas/Paralelo (AND)": "gateway.and",
    "Datos y sistemas/Sistema": "system",
    "Datos y sistemas/Documento": "document",
    "Datos y sistemas/Almacén de datos": "datastore",
    "Datos y sistemas/Anotación": "rule",
    "Marcadores/Paso modificado": "task",
    "Marcadores/Punto de dolor": "task",
    "Marcadores/Paso eliminado": "task",
    # English
    "Events/Start event": "event.start",
    "Events/Intermediate event": "event.intermediate",
    "Events/End event": "event.end",
    "Events/Off-page connector": "link",
    "Activities/Activity": "task",
    "Activities/Sub-process": "subprocess",
    "Gateways/Decision (XOR)": "gateway.xor",
    "Gateways/Parallel (AND)": "gateway.and",
    "Data and systems/System": "system",
    "Data and systems/Document": "document",
    "Data and systems/Data store": "datastore",
    "Data and systems/Annotation": "rule",
    "Markers/Changed step": "task",
    "Markers/Pain point": "task",
    "Markers/Removed step": "task",
}
COMPONENT_KEYS: dict[str, str] = {
    # "<published component key>": "task",   add your library's keys here (from figjam_extract.js output)
}
LANE_COMPONENTS = {"Marcadores/Carril", "Markers/Swimlane"}
HEADER_COMPONENTS = {"Plantilla/Bloque de cabecera", "Template/Header block"}
# Kept for code that imports the old names
LANE_COMPONENT, HEADER_COMPONENT = "Marcadores/Carril", "Plantilla/Bloque de cabecera"
CHANGE_MARKERS = {
    "Marcadores/Paso modificado": "changed", "Marcadores/Punto de dolor": "pain_point", "Marcadores/Paso eliminado": "removed",
    "Markers/Changed step": "changed", "Markers/Pain point": "pain_point", "Markers/Removed step": "removed",
}
# Retired arrow components (hidden from the published library). Using one is an R2 error with a clear fix.
RETIRED_COMPONENTS = {"Conectores/", "_Conectores/", "Connectors/", "_Connectors/"}
LABEL_PROPS = ("Etiqueta", "Pregunta", "Nota", "Letra", "Label", "Question", "Note", "Letter")
# Document link: share URL of the file (SharePoint, OneDrive, Drive), exported as node.url.
LINK_PROPS = ("Enlace", "Link")
SHOW_LINK_PROPS = ("Mostrar enlace", "Show link")
LINK_DEFAULTS = {"", "https://", "http://"}
LANE_PROPS = ("Rol", "Role")
# English header fields -> canonical (Spanish) field names
HEADER_ALIASES = {
    "Process ID": "ID del proceso", "Process name": "Nombre del proceso", "Owner": "Responsable",
    "Version": "Versión", "Status": "Estado", "Last updated": "Última actualización", "As-is / to-be": "Actual / futuro",
}

# Default texts of the library components (after whitespace normalisation). A label, lane
# role or header field still showing one was never filled in (R9).
PLACEHOLDERS = {
    "Verbo + objeto", "Subproceso [+]", "¿Pregunta?", "Nombre del evento", "Nombre del sistema",
    "Nombre del documento", "Almacén de datos", "Regla de negocio, KPI o nota", "Paso actual",
    "Paso actualizado", "Paso antiguo", "Rol / equipo", "Rol o nombre",
    "Verb + object", "Sub-process [+]", "Question?", "Event name", "System name",
    "Document name", "Data store", "Business rule, KPI or note", "As-is step",
    "Updated step", "Old step", "Role / team", "Role or name",
}
MAX_STEPS = 15  # tasks + subprocesses per diagram before W8 asks for a split

FLOW_TYPES = {"event.start", "event.intermediate", "event.end", "link", "task", "subprocess", "gateway.xor", "gateway.and"}
DATA_TYPES = {"system", "document", "datastore", "rule"}

STATUS_MAP = {"Borrador": "draft", "En revisión": "in-review", "Aprobado": "validated", "Obsoleto": "deprecated",
              "Draft": "draft", "In review": "in-review", "Approved": "validated", "Deprecated": "deprecated"}
STATE_MAP = {"Actual (as-is)": "as-is", "Futuro (to-be)": "to-be", "As-is": "as-is", "To-be": "to-be"}


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def areas() -> dict:
    return load_yaml(REPO / "governance" / "areas.yaml")["prefixes"]


def deep_link(file_key: str, node_id: str) -> str:
    return f"https://www.figma.com/board/{file_key}/?node-id={node_id.replace(':', '-')}"


# ---------------------------------------------------------------- normalisation

@dataclass
class Fix:
    node: str
    field: str
    before: str
    after: str


def clean(text, fixes: list[Fix], node: str, fld: str):
    """Mechanical autofixes allowed by rejection.ai_agent_may_autofix."""
    if not isinstance(text, str):
        return text
    after = re.sub(r"\s+", " ", text).strip()
    if after != text:
        fixes.append(Fix(node, fld, text, after))
    return after


def iso_date(text: str, fixes: list[Fix], node: str) -> str:
    m = re.fullmatch(r"(\d{2})[./-](\d{2})[./-](\d{4})", text)
    if m:
        after = f"{m[3]}-{m[2]}-{m[1]}"
        fixes.append(Fix(node, "Última actualización", text, after))
        return after
    return text


# ---------------------------------------------------------------- findings

@dataclass
class Finding:
    rule: str
    severity: str  # error | warning
    node: str | None
    label: str
    message: str


@dataclass
class Result:
    workflow: dict
    findings: list[Finding] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)

    @property
    def errors(self):
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == "warning"]


# ---------------------------------------------------------------- export + lint

def build(board: dict) -> Result:
    fixes: list[Fix] = []
    findings: list[Finding] = []
    src = board["source"]
    err = lambda r, n, l, m: findings.append(Finding(r, "error", n, l, m))
    warn = lambda r, n, l, m: findings.append(Finding(r, "warning", n, l, m))

    headers = [i for i in board["instances"] if i["component"] in HEADER_COMPONENTS]
    lanes_raw = [i for i in board["instances"] if i["component"] in LANE_COMPONENTS]
    for l in lanes_raw:  # normalise the English property name
        l["props"].setdefault("Rol", next((l["props"][k] for k in LANE_PROPS if k in l["props"]), ""))
    if len(headers) != 1:
        err("R1", None, "", f"Expected exactly one header block in the section, found {len(headers)}")
    hp = {HEADER_ALIASES.get(k, k): clean(v, fixes, headers[0]["id"] if headers else "-", k) for k, v in (headers[0]["props"] if headers else {}).items()}

    pid = hp.get("ID del proceso", "")
    if not re.fullmatch(r"[A-Z0-9]{2,6}-\d{2,3}(\.\d+)?", pid or ""):
        err("R1", headers[0]["id"] if headers else None, pid, "Process ID must look like AREA-NN or AREA-NNN, sub-process AREA-NN.n (e.g. P2P-03, OPS-001)")
    if not src["section_name"].startswith(pid or "\0"):
        err("R1", src["section_id"], src["section_name"], f"Section name must start with the process ID '{pid}'")
    prefix = (pid or "").split("-")[0]
    area = areas().get(prefix)
    if not area:
        err("R1", None, pid, f"Unknown area prefix '{prefix}'; add it to governance/areas.yaml")

    updated = iso_date(hp.get("Última actualización", ""), fixes, headers[0]["id"] if headers else "-")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", updated):
        err("R7", None, updated, "Header date must be YYYY-MM-DD")
    status = STATUS_MAP.get(hp.get("Estado", ""))
    if not status:
        err("R7", None, hp.get("Estado", ""), f"Header status must be one of {list(STATUS_MAP)}")
    state = STATE_MAP.get(hp.get("Actual / futuro", ""))
    if not state:
        err("R7", None, hp.get("Actual / futuro", ""), f"Header 'Actual / futuro' must be one of {list(STATE_MAP)}")
    declared = (hp.get("Versión") or "").lstrip("vV")
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", declared):
        err("R7", None, hp.get("Versión", ""), "Header version must look like v1.2.3")
    for fld, val in hp.items():
        if val in PLACEHOLDERS:
            err("R9", headers[0]["id"], val, f"Header field '{fld}' still shows the library default text; fill it in")

    # lanes
    lanes = sorted(lanes_raw, key=lambda l: l["y"])
    for a, b in zip(lanes, lanes[1:]):
        gap = b["y"] - (a["y"] + a["h"])
        if gap < 20:
            warn("W2", b["id"], b["props"].get("Rol", ""), f"Lane overlaps or is closer than 20 px to '{a['props'].get('Rol','')}' (gap {gap} px)")
    for l in lanes:
        role = clean(l["props"].get("Rol"), fixes, l["id"], "Rol")
        if not role:
            err("R6", l["id"], "", "Lane has no role name")
        elif role in PLACEHOLDERS:
            err("R9", l["id"], role, "Lane still shows the library default text; type the role or team")

    def lane_of(n):
        cx, cy = n["x"] + n["w"] / 2, n["y"] + n["h"] / 2
        hits = [l for l in lanes if l["y"] <= cy < l["y"] + l["h"] and l["x"] <= cx < l["x"] + l["w"]]
        return hits[0]["props"]["Rol"].strip() if len(hits) == 1 else None

    # nodes
    nodes: dict[str, dict] = {}
    markers = []
    for i in board["instances"]:
        if i["component"] in HEADER_COMPONENTS or i["component"] in LANE_COMPONENTS:
            continue
        if any((i["component"] or "").startswith(r) for r in RETIRED_COMPONENTS):
            err("R2", i["id"], i["component"], "Retired arrow component: delete it and draw a native FigJam connector between the two shapes (condition in the connector label)")
            continue
        t = COMPONENT_KEYS.get(i.get("component_key")) or COMPONENT_TYPES.get(i["component"])
        if not t:
            err("R2", i["id"], i["component"], "Component is not part of the Process Design Standards library")
            continue
        label = next((i["props"][p] for p in LABEL_PROPS if p in i["props"]), None)
        if label is None:  # e.g. pain point: the label lives in a nested step instance
            label = next((x for x in i.get("texts", []) if x.strip() and x.strip() not in ("!", "+")), "")
        n = {"id": i["id"], "type": t, "lane": lane_of(i) if t in FLOW_TYPES else None, "label": clean(label, fixes, i["id"], "label")}
        if t == "document":
            url = next((str(i["props"][p]).strip() for p in LINK_PROPS if p in i["props"]), "")
            shown = next((bool(i["props"][p]) for p in SHOW_LINK_PROPS if p in i["props"]), False)
            if url not in LINK_DEFAULTS:
                if re.fullmatch(r"https://\S+", url):
                    n["url"] = url
                else:
                    warn("W9", i["id"], n["label"], f"Document link '{url[:60]}' is not an https:// address; paste the share link (SharePoint, OneDrive, Drive), not a local path")
            elif shown:
                warn("W9", i["id"], n["label"], "Document shows a link but the Link / Enlace field is empty; paste the share URL or turn the link off")
        if i["component"] in CHANGE_MARKERS:
            n["change"] = CHANGE_MARKERS[i["component"]]
            markers.append(n)
        nodes[i["id"]] = n
        if t in FLOW_TYPES and n["lane"] is None:
            err("R6", i["id"], n["label"], "Step is not inside exactly one lane (checked at its centre point)")
        if n["label"] in PLACEHOLDERS:
            err("R9", i["id"], n["label"], "Label still shows the library default text; type the real label")
        elif t == "task" and len(n["label"].split()) < 2:
            warn("W1", i["id"], n["label"], "Task label should be verb + object (e.g. 'Approve invoice')")
        if t == "gateway.xor" and n["label"] and n["label"] not in PLACEHOLDERS and not n["label"].endswith("?"):
            warn("W7", i["id"], n["label"], "Decision label should be a yes/no question ending in '?' (e.g. 'Amount > €5,000?')")
        if t in FLOW_TYPES and not n["label"] and t not in ("gateway.and",):
            err("R2", i["id"], "", "Step has no label")
    steps = [n for n in nodes.values() if n["type"] in ("task", "subprocess")]
    if len(steps) > MAX_STEPS:
        warn("W8", None, "", f"{len(steps)} activities and sub-processes; the limit is {MAX_STEPS}. Collapse a group into a sub-process with its own section")
    for o in board.get("other", []):
        if o["type"] == "STICKY":
            warn("W4", o["id"], clean(o.get("text", ""), [], "", "")[:60], "Sticky note inside the process section; exported as a note, review before approval")
        elif o["type"] == "TEXT":
            warn("W3", o["id"], o.get("text", "")[:60], "Loose text is ignored by the export; use an annotation if it matters")
        else:
            err("R2", o["id"], (o.get("text") or o.get("name") or "")[:60], f"Off-library {o['type'].lower()}: insert the shape from Assets instead")

    # flows
    flows, assoc = [], []
    for c in board["connectors"]:
        f, t = c["from"], c["to"]
        lbl = clean(c.get("label", ""), fixes, c["id"], "connector label")
        if not f or not t:
            err("R3", c["id"], lbl, "Connector end is not attached to a shape")
            continue
        if f not in nodes or t not in nodes:
            what = "lane" if any(l["id"] in (f, t) for l in lanes) else "section, header or non-library shape"
            err("R3", c["id"], lbl, f"Connector is attached to a {what}; attach both ends to library steps")
            continue
        ft, tt = nodes[f]["type"], nodes[t]["type"]
        if ft in DATA_TYPES or tt in DATA_TYPES:
            if not c["dashed"]:
                err("R3", c["id"], lbl, "A link to a system, document, data store or rule must be a dashed (association) connector")
                continue
            assoc.append({"id": c["id"], "from": f, "to": t, "type": "association"})
            continue
        if c["dashed"]:
            flows.append({"id": c["id"], "from": f, "to": t, "type": "message", **({"condition": lbl} if lbl else {})})
        else:
            flows.append({"id": c["id"], "from": f, "to": t, "type": "sequence", **({"condition": lbl} if lbl else {})})

    # Reachability uses sequence AND message flows: a dashed handoff to another
    # organisation (e.g. supplier -> AP clerk) continues the process. Decision rules use
    # sequence flows only.
    out_, in_ = {k: [] for k in nodes}, {k: [] for k in nodes}
    for x in flows:
        out_[x["from"]].append(x)
        in_[x["to"]].append(x)
    starts = [n for n in nodes.values() if n["type"] == "event.start"]
    if len(starts) != 1:
        err("R5", None, ", ".join(s["label"] for s in starts), f"Expected exactly one start event, found {len(starts)}")
    for n in nodes.values():
        if n["type"] not in FLOW_TYPES:
            continue
        nid, lbl = n["id"], n["label"]
        if n["type"] == "event.end" and out_[nid]:
            err("R5", nid, lbl, "End event has an outgoing flow; use a dashed message flow or an intermediate event")
        if n["type"] != "event.start" and not in_[nid]:
            err("R5", nid, lbl, "Not reachable: no incoming flow")
        if n["type"] not in ("event.end", "link") and not out_[nid]:
            err("R5", nid, lbl, "Dead end: no outgoing flow")
        if n["type"] == "gateway.xor":
            exits = [x for x in out_[nid] if x["type"] == "sequence"]
            if len(exits) < 2:
                err("R4", nid, lbl, f"Decision has {len(exits)} exit(s); it needs at least two")
            labels = [x.get("condition") for x in exits]
            if any(not l for l in labels):
                err("R4", nid, lbl, "Every exit from a decision needs a condition label on the connector")
            if len(set(filter(None, labels))) != len(list(filter(None, labels))):
                err("R4", nid, lbl, "Exit labels on one decision must be unique")
        elif n["type"] != "gateway.and" and any("condition" in x for x in out_[nid] if x["type"] == "sequence"):
            warn("R4", nid, lbl, "Conditional exit from a step that is not a decision; add a decision shape")
    if len(starts) == 1:
        seen, todo = set(), [starts[0]["id"]]
        while todo:
            k = todo.pop()
            if k in seen:
                continue
            seen.add(k)
            todo += [x["to"] for x in out_[k]]
        for n in nodes.values():
            if n["type"] in FLOW_TYPES and n["id"] not in seen and in_[n["id"]]:
                err("R5", n["id"], n["label"], "Not reachable from the start event")
    for n in nodes.values():
        if n["type"] in DATA_TYPES and not any(n["id"] in (a["from"], a["to"]) for a in assoc):
            warn("W5", n["id"], n["label"], f"{n['type'].capitalize()} is not linked to any step")
    for m in markers:
        if m["change"] == "removed" and status in ("in-review", "validated"):
            err("R8", m["id"], m["label"], "Removed-step marker in a diagram going to review/approval: delete the step once the change is agreed")
        if m["change"] == "pain_point" and state == "to-be":
            warn("W6", m["id"], m["label"], "Pain-point marker belongs in as-is diagrams")
        if m["change"] in ("changed", "removed") and state == "as-is":
            warn("W6", m["id"], m["label"], "Changed/removed-step markers belong in to-be diagrams")

    notes = [{"id": o["id"], "author": o.get("author", ""), "text": clean(o.get("text", ""), [], "", "")} for o in board.get("other", []) if o["type"] == "STICKY"]

    wf = {
        "schema_version": SCHEMA_VERSION,
        "process": {
            "id": pid,
            "name": hp.get("Nombre del proceso", ""),
            "area": area or "unknown",
            "owner": hp.get("Responsable", ""),
            "version": "0.0.0",
            "declared_version": hp.get("Versión", ""),
            "status": status or "draft",
            "updated": updated,
            "state": state or "as-is",
            "source": {
                "figma_file_key": src["figma_file_key"],
                "figma_page_or_section": src["section_id"],
                "exported_at": src["exported_at"],
                "exported_by": board.get("extractor", ""),
                **({"figma_version_id": str(src["figma_version_id"])} if src.get("figma_version_id") else {}),
            },
            "content_hash": "",
        },
        "lanes": [{"id": l["id"], "role": l["props"]["Rol"].strip()} for l in lanes],
        "nodes": list(nodes.values()),
        "flows": flows,
        "associations": assoc,
    }
    if wf["process"]["status"] == "validated":
        # Header "Aprobado" only claims approval. The claim becomes true when a business SME
        # code owner approves the intake PR (branch protection); workflow_release.py verifies
        # that approval on the merged PR before it tags anything.
        wf["process"]["validated_by"] = {"role": "Business SME (CODEOWNERS approval of the intake PR)", "date": updated}
    if notes:
        wf["notes"] = notes
    wf["process"]["content_hash"] = content_hash(wf)
    return Result(wf, findings, fixes)


def content_hash(wf: dict) -> str:
    """Hash of everything that defines behaviour; excludes volatile provenance and version fields."""
    core = {k: v for k, v in wf.items() if k != "process"}
    core["process"] = {k: v for k, v in wf["process"].items() if k not in ("version", "declared_version", "source", "content_hash", "updated", "validated_by")}
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def schema_errors(wf: dict) -> list[str]:
    import jsonschema
    schema = json.loads((REPO / "schemas" / "workflow.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in v.iter_errors(wf)]


# ---------------------------------------------------------------- versioning

def _sv(s):
    return tuple(int(x) for x in s.split("."))


def diff(old: dict | None, new: dict) -> tuple[str, list[str]]:
    """Return (bump, reasons) following versioning.bump_rules."""
    if old is None:
        return "initial", ["First export"]
    reasons = {"major": [], "minor": [], "patch": []}
    on, nn = {n["id"]: n for n in old["nodes"]}, {n["id"]: n for n in new["nodes"]}
    for k in on.keys() - nn.keys():
        if on[k]["type"] in FLOW_TYPES:
            reasons["major"].append(f"Removed {on[k]['type']} '{on[k]['label']}'")
        else:
            reasons["minor"].append(f"Removed {on[k]['type']} '{on[k]['label']}'")
    for k in nn.keys() - on.keys():
        reasons["minor"].append(f"Added {nn[k]['type']} '{nn[k]['label']}'")
    for k in on.keys() & nn.keys():
        a, b = on[k], nn[k]
        if a["type"] != b["type"]:
            reasons["major"].append(f"'{a['label']}' changed type {a['type']} -> {b['type']}")
        if a.get("lane") != b.get("lane"):
            reasons["major"].append(f"'{a['label']}' moved lane {a.get('lane')} -> {b.get('lane')}")
        if a["label"] != b["label"]:
            reasons["patch"].append(f"Label '{a['label']}' -> '{b['label']}' (confirm the meaning is unchanged)")
        if a.get("url") != b.get("url"):
            reasons["patch"].append(f"Link of '{b['label']}' changed")
    of = {(f["from"], f["to"]): f for f in old["flows"]}
    nf = {(f["from"], f["to"]): f for f in new["flows"]}
    for k in of.keys() - nf.keys():
        reasons["major"].append(f"Removed or retargeted flow {k[0]} -> {k[1]}")
    for k in nf.keys() - of.keys():
        reasons["minor"].append(f"Added flow {k[0]} -> {k[1]}")
    for k in of.keys() & nf.keys():
        if of[k].get("condition") != nf[k].get("condition"):
            reasons["major"].append(f"Condition on {k[0]} -> {k[1]} changed '{of[k].get('condition')}' -> '{nf[k].get('condition')}'")
    if {l["role"] for l in old["lanes"]} - {l["role"] for l in new["lanes"]}:
        reasons["major"].append("Lane removed or renamed")
    oa = {(a["from"], a["to"]) for a in old.get("associations", [])}
    na = {(a["from"], a["to"]) for a in new.get("associations", [])}
    if na - oa:
        reasons["minor"].append("Added association(s)")
    if oa - na:
        reasons["minor"].append("Removed association(s)")
    if old["process"].get("status") != new["process"].get("status"):
        reasons["patch"].append(f"Status {old['process'].get('status')} -> {new['process'].get('status')}")
    if old["process"].get("owner") != new["process"].get("owner"):
        reasons["patch"].append("Owner changed")
    for level in ("major", "minor", "patch"):
        if reasons[level]:
            return level, reasons[level] + [r for l2 in ("major", "minor", "patch") if l2 != level for r in reasons[l2]]
    return "none", []


def next_version(old: dict | None, new: dict, bump: str) -> str:
    validated = new["process"]["status"] == "validated"
    if old is None:
        return "1.0.0" if validated else "0.1.0"
    ma, mi, pa = _sv(old["process"]["version"])
    if validated and ma == 0:
        return "1.0.0"
    if bump == "none":
        return old["process"]["version"]
    if ma == 0:  # pre-release: shift down one level
        bump = {"major": "minor", "minor": "patch", "patch": "patch"}[bump]
    return {"major": f"{ma + 1}.0.0", "minor": f"{ma}.{mi + 1}.0", "patch": f"{ma}.{mi}.{pa + 1}"}[bump]


# ---------------------------------------------------------------- paths

def paths(wf: dict) -> dict:
    p = wf["process"]
    return {
        "dir": REPO / "workflows" / p["area"] / p["id"],
        "page": REPO / "docs" / "processes" / p["area"] / f"{p['id']}.md",
        "scenarios": REPO / "conformance" / p["id"] / "scenarios.feature",
    }
