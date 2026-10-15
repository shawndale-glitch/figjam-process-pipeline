# FigJam process pipeline

Turns process diagrams drawn in FigJam into validated, versioned, machine-readable workflows, and checks the process inventory workbook they're planned from.

A business analyst draws a process in FigJam with a shared component library. The pipeline reads the diagram, checks it against written rules, and, if it passes, writes:

- `workflows/<area>/<ID>/workflow.yaml`: the process as data (steps, lanes, flows, conditions, linked systems and documents);
- `docs/processes/<area>/<ID>.md`: a human page with a Mermaid flowchart;
- `conformance/<ID>/scenarios.feature`: one Gherkin scenario per path, for application teams.

If it fails, the author gets a report with one line per problem and a link to the exact shape on the board.

## How it works

```text
FigJam process section
   │  tooling/figjam_extract.js   (Figma plugin API)   or   tooling/figma_rest.py   (REST API)
   ▼
board.json          facts only: components, properties, positions, connectors, line styles
   │  tooling/workflow_intake.py
   ▼
lint (R1–R9, W1–W8) → schema → semantic diff → version → workflow.yaml + page + scenarios
```

- **Rules** live in [`governance/workflow-rules.yaml`](governance/workflow-rules.yaml): board rules under `lint`, inventory rules under `inventory`, plus versioning, rejection and conformance policy. The code follows that file.
- **Versioning** is computed from a semantic diff of `workflow.yaml`: a removed step or changed condition is a major bump, an added step is a minor, a wording change is a patch.
- **Inventory check:** `tooling/inventory_check.py` validates the `.xlsx` that lists the processes to be drawn (required columns, IDs, ISO dates, statuses, FigJam links, and agreement with `workflows/`).
- **Conformance:** `tooling/workflow_conformance.py` and the reusable workflow let application repos check that what they built matches a released process version.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python tooling/selftest.py      # every rule must fire on a broken board, and clean boards must pass
python tooling/workflow_intake.py examples/library-selftest/P2P-03-template.board.json --dry-run
python tooling/inventory_check.py path/to/inventory.xlsx
```

To read a real board, run `tooling/figjam_extract.js` through the Figma plugin API (for example the Figma MCP `use_figma` tool) with `FILE_KEY`, `PAGE_ID` and `SECTION_ID` filled in, and save the result as `board.json`. In CI, `workflow_intake.py --url "<FigJam section link>"` reads it through the REST API with a `FIGMA_TOKEN`.

## Using your own component library

The rules expect a FigJam library with these components, in English or Spanish: start, intermediate and end events, off-page connector, activity, sub-process, XOR and AND gateways, system, document, data store, annotation, changed/pain-point/removed step markers, swimlane and a header block. Component names are listed in `COMPONENT_TYPES` in `tooling/workflow_core.py`; add your published component keys to `COMPONENT_KEYS` so renamed components still map. Flows are native FigJam connectors: solid = sequence, dashed between steps = handoff, dashed or dotted to a system, document, data store or annotation = association.

## Layout

```text
governance/   workflow-rules.yaml (the rules), areas.yaml (allowed process ID prefixes)
schemas/      workflow.schema.json (the contract for workflow.yaml)
tooling/      extractor, intake, render, release, conformance, inventory check, self-test
examples/     library-selftest/: boards that use every component
conformance/  bindings.template.yaml for application teams
workflows/    consumers.yaml (which apps implement which process versions)
.github/      CI (self-test) and the intake, release and conformance workflows
```

## Status

- The plugin-API extractor, intake, inventory check and self-test have been run against real boards.
- `figma_rest.py` (the REST reader used by CI intake) hasn't yet been run against the live Figma API.
- The examples are fictional.

## License

Copyright © 2026 Shawn Dale. All rights reserved. The code is published for reading and reference; no license is granted to copy, modify or redistribute it.
