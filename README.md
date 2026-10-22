# FigJam Process Pipeline

**Turns process diagrams drawn by business teams in FigJam into validated, versioned, machine-readable workflows that developers, testers and AI agents can build against.**

This project explores one question:

> How do you get a whiteboard drawing, made collaboratively by people who aren't modellers, to become a contract that software can be checked against?

Instead of treating a process diagram as a picture, the pipeline treats it as **source data**: every shape comes from a shared component library, every line has a meaning, and the board is read as facts, checked against written rules, versioned by what actually changed, and published as YAML, a documentation page and test scenarios. A board that breaks the rules is never "fixed up" silently. Its author gets one line per problem and a link to the exact shape.

| If you have… | Read |
|---|---|
| 30 seconds | This page, down to [Why this matters](#why-this-matters) |
| 5 minutes | The [rule catalogue](governance/workflow-rules.yaml) and one [example board](examples/patterns/README.md) |
| 20 minutes | The [tooling](tooling/README.md), the [self-test](tooling/selftest.py) and the [schema](schemas/workflow.schema.json) |
| An interview slot | The [walkthrough](WALKTHROUGH.md): a 15-minute live demo of this repository |

## What this demonstrates

- Treating diagrams as structured, machine-readable source content
- A rule catalogue as configuration (`workflow-rules.yaml`), read by code, CI and reviewers alike
- Validation gates that explain themselves: rule ID, the shape's label and a deep link to it
- Semantic versioning computed from a diff of the process, not chosen by hand
- Docs-as-code outputs from one source: data (`workflow.yaml`), a page (Mermaid) and tests (Gherkin)
- Governance for collaborative authoring: drafts, review by a business owner, release tags
- Conformance checks that let application teams prove their build matches a released process version
- Validation of the planning spreadsheet the diagrams are scheduled from
- A self-test that proves every rule fires, run in CI on every push
- AI in the loop with a human gate: an assistant can extract a board, report and propose fixes, but a release needs a pull request approved by someone other than its author

## Architecture

![Pipeline: a FigJam section is extracted to board.json, checked by the validation gate, then either reported back to the author or versioned and published as workflow.yaml, a process page and Gherkin scenarios, reviewed, released and checked by application repositories](diagrams/pipeline.svg)

```text
              FIGJAM BOARD  (shared component library, one section per process)
                      │
                      │  tooling/figjam_extract.js (plugin API)  or  tooling/figma_rest.py (REST, for CI)
                      ▼
                 board.json                   ← facts only: components, props, positions, connectors
                      │
                      │  tooling/workflow_intake.py
                      ▼
        VALIDATION GATE  R1–R9 · W1–W8 · schema   ← rules from governance/workflow-rules.yaml
           │                          │
      rejected                    accepted
           ▼                          ▼
   report to the author        semantic diff → version
   (nothing written)                  │
                     ┌────────────────┼────────────────┐
                     ▼                ▼                ▼
              workflow.yaml     process page     scenarios.feature
                     │
                     ▼
        pull request → business-owner approval → tag <ID>@<semver> → conformance in app repos
```

## Why this matters

Process workshops produce drawings. Delivery teams need contracts. The gap between the two is usually closed by someone re-typing the diagram into a spec, and the spec and the board drift apart from that day on.

Closing the gap needs a few things that a whiteboard doesn't give you by default:

- **one meaning per shape**, so a machine can tell an activity from a decision from a system
- **explicit flow semantics**: sequence, hand-off and association are different lines
- **every step owned by a role**, so the process says who does what
- **a version that means something**: a removed step is a breaking change, a rewording isn't
- **feedback the author can act on**, in the author's own words and on the author's own board
- **a review step a business owner signs**, before anything is called "validated"

This pipeline makes each of those a rule, enforces it with tooling, and keeps the people drawing the process in charge of the content.

## Example

Real first-session boards fail in predictable ways: the legend gets pasted into the process area, a decision exit has no condition, a system is joined with a solid line, another is left floating. The self-test reproduces exactly that on the fictional invoice-approval example, and the gate reports:

```text
## Findings: 5 errors, 2 warnings

- ❌ R2 «» Off-library section: insert the shape from Assets instead (open in FigJam)
- ❌ R3 «» A link to a system, document, data store or rule must be a dashed (association) connector (open in FigJam)
- ❌ R5 «Goods delivered, Order received» Expected exactly one start event, found 2
- ❌ R4 «PO matches?» Every exit from a decision needs a condition label on the connector (open in FigJam)
- ❌ R5 «Order received» Dead end: no outgoing flow (open in FigJam)
- ⚠️ W5 «ERP» System is not linked to any step (open in FigJam)
- ⚠️ W5 «Spreadsheet» System is not linked to any step (open in FigJam)
```

Every line names the rule, quotes the label the author typed, and links to the shape. Fixed, the same board passes with 0 findings and is published as data. For the pattern teams use to say *which system, which document, when, and with what data* for each step, see [`examples/patterns/`](examples/patterns/README.md).

## Try it

The examples are small, fictional and valid. The self-test runs them, then breaks copies on purpose to prove each rule fires.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python tooling/selftest.py
python tooling/workflow_intake.py examples/patterns/QA-003-activity-pattern.board.json --dry-run
```

To read a real board, run `tooling/figjam_extract.js` through the Figma plugin API (for example the Figma MCP `use_figma` tool) with `FILE_KEY`, `PAGE_ID` and `SECTION_ID` filled in, and save the result as `board.json`. In CI, `workflow_intake.py --url "<FigJam section link>"` reads it through the REST API with a `FIGMA_TOKEN`. To check a planning workbook: `python tooling/inventory_check.py path/to/inventory.xlsx`.

CI runs the self-test and a strict docs build on every push. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## The rules at a glance

| Errors (block) | Warnings (block only at review) |
|---|---|
| **R1** one header; process ID format and known area | **W1** activity labels are verb + object |
| **R2** library shapes only; every step labelled | **W2** lanes don't overlap |
| **R3** connectors attached at both ends; associations dashed | **W3** no loose text in the process |
| **R4** decisions have ≥ 2 exits with unique conditions | **W4** sticky notes are reviewed before approval |
| **R5** one start; everything reachable; no dead ends | **W5** systems, documents and notes are linked to a step |
| **R6** every step sits in exactly one role lane | **W6** markers match as-is / to-be |
| **R7** header date, status and version use allowed values | **W7** a decision label is a question |
| **R8** no "removed step" marker at review | **W8** at most 15 activities per diagram |
| **R9** no library placeholder text left behind | |

The planning workbook has its own catalogue (I1–I8). Full wording, rationale and the versioning, rejection and conformance policies are in [`governance/workflow-rules.yaml`](governance/workflow-rules.yaml).

## Repository map

```text
.
├── README.md                 # you are here
├── WALKTHROUGH.md            # what I demonstrate live in an interview
├── governance/               # workflow-rules.yaml (the rules), areas.yaml (allowed ID prefixes)
├── schemas/                  # workflow.schema.json: the contract for workflow.yaml
├── tooling/                  # extractor, intake, render, release, conformance, inventory check, self-test
├── examples/                 # library-selftest/ (every component) and patterns/ (recommended authoring)
├── diagrams/                 # pipeline diagram (SVG)
├── conformance/              # bindings template for application teams
├── workflows/                # consumers.yaml: which apps implement which process versions
├── docs/                     # where generated process pages land (MkDocs)
└── .github/workflows/        # CI self-test, and the intake, release and conformance workflows
```

## Technology and tooling

- FigJam with a published component library (Spanish and English), native connectors
- Figma Plugin API and REST API for extraction
- Python for linting, versioning, rendering, release and conformance
- YAML for rules and workflows, JSON Schema for the workflow contract
- Mermaid for diffable flowcharts, Gherkin for executable scenarios
- MkDocs Material with strict builds
- GitHub Actions for CI, intake pull requests, release tagging and reusable conformance checks
- Claude with the Figma MCP server for extraction, review and AI-assisted board fixes, with a person approving every release

## Project status

This is a working proof of concept, used on real process-redesign sessions.

- The plugin-API extractor, intake, inventory check and self-test have been run against real boards.
- `figma_rest.py` (the REST reader used by CI intake) hasn't yet been run against the live Figma API.

The **production implementation** runs in a private repository because the processes are a client's. Everything here is a sanitized, clean-room presentation: the examples are a **fictional invoice-approval process** and a **generic front-desk check-in**, component keys and file keys are placeholders, and no client material is included.

## About

Designed and implemented by **Shawn Dale**, principal-level technical documentation professional specializing in documentation architecture, developer experience, APIs, AI-assisted documentation, and structured knowledge systems.

> Diagrams are documentation too. This makes them documentation a machine can hold you to.

Related: [AI-Native Documentation Architecture](https://github.com/shawndale-glitch/ai-documentation-architecture), the content model this pipeline's outputs are designed to sit in.

## License

Copyright © 2026 Shawn Dale. All rights reserved. The code is published for reading and reference; no license is granted to copy, modify or redistribute it. See [LICENSE](LICENSE).
