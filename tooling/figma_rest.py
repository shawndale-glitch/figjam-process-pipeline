"""Figma REST API -> board.json (the same shape tooling/figjam_extract.js returns).

Used by workflow_intake.py --url in CI, where the plugin API isn't available.
Needs a Figma token with read access to the board, in FIGMA_TOKEN.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.figma.com/v1"
EXTRACTOR = "figma_rest.py@2"


def parse_url(url: str) -> tuple[str, str]:
    """Return (file_key, node_id) from a figma.com/board/... link with ?node-id=."""
    m = re.search(r"figma\.com/board/([0-9A-Za-z]+)", url)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if not m or "node-id" not in q:
        raise ValueError("Expected a FigJam link to the process section: https://www.figma.com/board/<key>/...?node-id=<id>")
    return m.group(1), q["node-id"][0].replace("-", ":")


def fetch(file_key: str, node_id: str, token: str | None = None) -> dict:
    token = token or os.environ.get("FIGMA_TOKEN")
    if not token:
        raise RuntimeError("FIGMA_TOKEN is not set")
    url = f"{API}/files/{file_key}/nodes?ids={urllib.parse.quote(node_id)}"
    req = urllib.request.Request(url, headers={"X-Figma-Token": token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _props(raw: dict) -> dict:
    return {k.split("#")[0]: v.get("value") for k, v in (raw or {}).items()}


def _texts(node: dict) -> list[str]:
    out = []
    for c in node.get("children", []):
        if c.get("type") == "TEXT":
            out.append(c.get("characters", ""))
        out += _texts(c)
    return out


def to_board(resp: dict, file_key: str, node_id: str) -> dict:
    """Convert a GET /v1/files/:key/nodes response into board.json."""
    entry = resp["nodes"].get(node_id)
    if not entry or not entry.get("document"):
        raise ValueError(f"Node {node_id} not found in file {file_key}")
    section = entry["document"]
    if section.get("type") != "SECTION":
        raise ValueError(f"Node {node_id} is a {section.get('type')}, not a section. Link to the process section.")
    components = entry.get("components", {})
    sb = section["absoluteBoundingBox"]

    def rel(n):
        b = n.get("absoluteBoundingBox") or {}
        if not b:
            return {}
        return {"x": round(b["x"] - sb["x"]), "y": round(b["y"] - sb["y"]), "w": round(b["width"]), "h": round(b["height"])}

    board = {
        "extractor": EXTRACTOR,
        "source": {
            "figma_file_key": file_key,
            "page_id": None,
            "section_id": section["id"],
            "section_name": section.get("name", ""),
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "figma_version_id": resp.get("version"),
        },
        "instances": [], "connectors": [], "other": [],
    }

    def walk(n, parent_type):
        for c in n.get("children", []):
            t = c.get("type")
            if t == "INSTANCE":
                comp = components.get(c.get("componentId"), {})
                board["instances"].append({
                    "id": c["id"], "component": comp.get("name"), "component_key": comp.get("key"),
                    "remote": comp.get("remote"), "props": _props(c.get("componentProperties")), "texts": _texts(c), **rel(c)})
                continue  # never descend into instances
            if t == "CONNECTOR":
                s, e = c.get("connectorStart", {}), c.get("connectorEnd", {})
                board["connectors"].append({
                    "id": c["id"], "from": s.get("endpointNodeId"), "to": e.get("endpointNodeId"),
                    "label": c.get("characters", ""), "dashed": bool(c.get("strokeDashes")),
                    "start_cap": c.get("connectorStartStrokeCap"), "end_cap": c.get("connectorEndStrokeCap")})
                continue
            if t in ("SHAPE_WITH_TEXT", "STICKY", "TEXT", "FRAME", "GROUP", "SECTION") and parent_type != "FRAME":
                o = {"id": c["id"], "type": t, "name": c.get("name", ""), **rel(c)}
                if t in ("SHAPE_WITH_TEXT", "STICKY", "TEXT"):
                    o["text"] = c.get("characters", "")
                if t == "STICKY":
                    o["author"] = ""  # the REST API doesn't expose sticky authors
                if t == "FRAME":
                    o["text"] = " ".join(_texts(c))
                board["other"].append(o)
            walk(c, t)

    walk(section, "SECTION")
    return board


def extract(url: str, token: str | None = None) -> dict:
    key, node = parse_url(url)
    return to_board(fetch(key, node, token), key, node)
