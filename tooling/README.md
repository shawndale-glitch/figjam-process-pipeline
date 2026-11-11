# Tooling

Scripts for the FigJam → repository workflow pipeline. Rules: [`governance/workflow-rules.yaml`](../governance/workflow-rules.yaml). Overview: [`README.md`](../README.md).

## Pipeline

```text
FigJam section ──figjam_extract.js──▶ board.json ──workflow_intake.py──▶ lint + schema + version
                                                        │
                    rejected (exit 1): report only, nothing written
                    accepted (exit 0): writes the resting point ▼
   workflows/<area>/<ID>/workflow.yaml, board.json, CHANGELOG.md
   docs/processes/<area>/<ID>.md      conformance/<ID>/scenarios.feature
```

| Script | Status | What it does |
|---|---|---|
| `figjam_extract.js` | Working (plugin API) | Reads one process section from a FigJam board and returns `board.json`: facts only (components, properties, positions, connectors). Run through the Figma MCP `use_figma` tool or a plugin. |
| `workflow_intake.py` | Working | `board.json` → lint (R1–R9, W1–W9; catalogue in `workflow-rules.yaml` → `lint`) → schema → semantic diff and version → writes the resting point. Exit 1 and a report if anything blocks. |
| `inventory_check.py` | Working | Checks the process inventory workbook (`.xlsx`) against `workflow-rules.yaml` → `inventory` (I1–I8): required columns, process IDs, ISO dates, statuses, area-column key, FigJam links, and agreement with `workflows/`. Exit 1 on errors. |
| `workflow_core.py` | Working | Shared rules: component mapping, lane assignment, lint, content hash, version bump. |
| `figma_rest.py` | Working, not yet run against the live API | Same `board.json` shape from `GET /v1/files/:key/nodes`, so CI runs without the plugin. Used by `workflow_intake.py --url`. |
| `workflow_render.py` | Working | Renders the process page (Mermaid, steps, rules) and the Gherkin scenarios; also callable on its own. |
| `workflow_release.py` | Working | After merge: releases changed `validated` workflows. Checks the merged PR was approved by someone other than its author, tags `<ID>@<semver>`, builds the bundle, creates the GitHub release, opens issues in consumer repos on a major. |
| `workflow_conformance.py` | Working | In consumer repos: `resolve` picks the newest release in the pinned range; `check` runs C1 traceability (bindings resolve to OpenAPI operationIds / AsyncAPI events, every decision exit mapped) and C4 evidence for the happy path. |
| `procedure_check.py` | Working | Checks `procedures/*/*/procedure.yaml` against `workflow-rules.yaml` → `procedure` (P1–P9, PW1–PW2) and the schema; role and step must exist on the linked process in `workflows/`. |
| `procedure_run.py` | Working | Runs a procedure against its system once per language: fixtures through the system's API, narration (Windows SAPI, Piper or none), Playwright run with captions and highlights, `verify` through the API, then a 1080p MP4 with subtitles, step screenshots and a QA report in `build/procedures/<id>/<lang>/`. `starts_from` procedures run first, off camera. `--start-demo` starts Paydesk. |
| `procedure_render.py` | Working | Writes the guide page per procedure (one tab per language: steps, expected results, screenshots, video, QA stamp) and `docs/procedures/index.md`. |
| `demo.py` | Working | The two-act demo in one command: starts Paydesk and runs every procedure (English, no narration), then restarts it with `--drift` and shows the approval guide failing at the renamed button. `--headed` to watch, `--serve` to keep Paydesk running afterwards. Exit 0 only if act 1 passes and act 2 fails. |
| `procedure_core.py` | Working | Shared procedure rules: schema, lint, languages per system, `starts_from` chains. |
| `selftest.py` | Working | Runs the library self-test boards (`examples/library-selftest/`) through intake: every published component must pass with 0 findings. Then breaks copies on purpose: a retired arrow component, default texts (R9), a decision that isn't a question (W7), more than 15 activities (W8), a good and a broken inventory workbook must each give the expected result, and every example procedure must pass while copies broken on purpose trigger P2–P9, PW1 and PW2. |

## Which Action calls what

| Action | Script | Trigger |
|---|---|---|
| `.github/workflows/workflow-intake.yml` | `workflow_intake.py --url` | Manual (section link). Accepted → PR `workflow/<ID>-<version>`; rejected → issue labelled `workflow:validation-failed`. |
| `.github/workflows/workflow-release.yml` | `workflow_release.py --since` | Push to `main` touching `workflows/**/workflow.yaml` |
| `.github/workflows/workflow-conformance.yml` | `workflow_conformance.py resolve` + `check` | Called from consumer repos (reusable workflow); C2 runs the consumer's own scenario command |

Secrets: `FIGMA_TOKEN` (required for intake), `INTAKE_BOT_TOKEN` (optional, lets CI run on intake PRs), `CONSUMER_NOTIFY_TOKEN` (optional, cross-repo issues), and `docs_repo_token` in consumer repos while this repo is private.

## Run it

```bash
pip install -r requirements.txt
python tooling/workflow_intake.py path/to/board.json --report intake-report.md
FIGMA_TOKEN=... python tooling/workflow_intake.py --url "https://www.figma.com/board/<key>/...?node-id=<section>"
python tooling/workflow_release.py --since <sha> --dry-run
python tooling/workflow_conformance.py check --model workflow.yaml --bindings bindings.yaml --range ^1.0.0 --openapi "api/*.yaml"
python tooling/inventory_check.py path/to/inventory.xlsx --report inventory-report.md
python tooling/selftest.py
mkdocs build --strict
```

Run `figjam_extract.js` through `use_figma` with `FILE_KEY`, `PAGE_ID` and `SECTION_ID` filled in, save the returned object as `board.json`, then pass it to `workflow_intake.py` (add `--dry-run` to check without writing anything).

New process areas need a prefix in [`governance/areas.yaml`](../governance/areas.yaml). A new process page also needs a `nav` entry in `mkdocs.yml`; the intake report says so when it's missing.
