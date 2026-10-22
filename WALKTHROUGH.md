# Interview walkthrough

A 15-minute live demonstration that runs entirely from this repository. The production implementation is private because the processes belong to a client, so I don't screen-share it; everything below shows the same pipeline working on fictional processes.

## 1. The problem (2 min)

Open the [README](README.md#why-this-matters).

- Process workshops produce drawings; delivery teams need contracts. Usually someone re-types the board into a spec, and the two drift apart.
- The pipeline makes the board itself the source: shared components, meaningful lines, written rules, computed versions.
- The people who draw the process stay in charge of the content. The tooling only checks form and records change.

## 2. A board is data (3 min)

Open [`examples/patterns/QA-003-activity-pattern.board.json`](examples/patterns/QA-003-activity-pattern.board.json), then the [pattern it encodes](examples/patterns/README.md).

- The extractor records **facts only**: which component, which properties, where it sits, what each connector joins and whether it's dashed.
- All interpretation happens in Python against the rules file, so the same `board.json` can be re-checked when the rules change.
- The pattern answers the questions teams actually ask in sessions: which system, which list or document, at what moment, with what data.

## 3. The gate (4 min)

Run it live:

```bash
python tooling/selftest.py
```

- Four clean boards pass with 0 findings; then broken copies prove every newer rule fires.
- The **first-session mistakes** case reproduces what real boards get wrong: legend pasted inside the process, an unlabelled decision exit, a solid line to a system, a system left floating. One run catches all of them.

Then break something yourself: open the pattern board, change a dashed connector to `"dashed": false`, and run

```bash
python tooling/workflow_intake.py examples/patterns/QA-003-activity-pattern.board.json --dry-run
```

The report names the rule (R3), quotes the label and links to the shape.

## 4. Versions that mean something (2 min)

Open [`governance/workflow-rules.yaml`](governance/workflow-rules.yaml) at `versioning`.

- The version is computed from a semantic diff of `workflow.yaml`: a removed step or changed condition is a **major**, an added step is a **minor**, a wording change is a **patch**.
- The board header must declare the computed version, so the diagram and the repository can't disagree about what changed.
- A release needs a pull request approved by someone other than its author; a major opens an issue in every consuming application repo.

## 5. From process to tests and conformance (2 min)

Run intake without `--dry-run` on the worked example, then open the generated page and scenarios:

```bash
python tooling/workflow_intake.py examples/library-selftest/P2P-03-template.board.json
```

- `docs/processes/…`: a Mermaid flowchart and a step table for people.
- `conformance/P2P-03/scenarios.feature`: one Gherkin scenario per path for testers.
- [`conformance/bindings.template.yaml`](conformance/bindings.template.yaml): how an application team maps each step to an API operation or event, so `workflow_conformance.py` can check their build against a pinned version range.

## 6. The planning spreadsheet (1 min)

`tooling/inventory_check.py` validates the workbook the sessions are planned from: IDs, ISO dates, statuses, links to each board, and agreement with what's already in `workflows/`. Planning errors surface before a session, not after.

## 7. AI in the workflow (1 min)

- An assistant with the Figma MCP server extracts boards, runs the gate and proposes fixes; on a real first draft with over a hundred errors it produced a corrected copy that passed, and listed the three changes that altered the process's logic for the team to confirm.
- It never decides what a process *is*: anything that changes meaning is flagged for a person, and nothing is released without a human approval.

## Questions I expect

| Question | Short answer |
|---|---|
| Why not BPMN tooling? | The people who know the process already work in FigJam. A small, opinionated component set gets 90% of BPMN's semantics without asking them to change tools. |
| Isn't this rigid for workshops? | Only inside the process section. Brainstorms, Venn diagrams and notes beside it are never read. Drafts can carry warnings; only review and release are strict. |
| What if the library changes? | Component keys are pinned and names are a fallback; the self-test boards use every component, so a library change that breaks mapping fails CI. |
| What's implemented versus designed? | See [Project status](README.md#project-status): everything except the live REST extractor has run against real boards. |
