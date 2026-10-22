# Authoring patterns

Recommended ways to draw common situations so the board stays readable for people **and** passes the gate. Each pattern has a board extracted to `board.json`; `tooling/selftest.py` runs it, so a pattern can never silently stop passing.

## QA-003 Activity pattern: action, system, document, moment and data

**Question it answers:** "For each step, how do we show where it's done, what list or document it needs, *when* it happens and *what data* it uses?"

| What you want to show | Library shape | How it joins the step |
|---|---|---|
| The **action** | Activity, labelled verb + object: "Verify booking" | Solid connector with arrow, step to step |
| The **system** where it's done | System: "PMS" | Dashed connector, no arrows |
| A **list or document** it needs | Document: "Arrivals list" (use Data store if the list is a query inside the system); paste its share URL in the **Link** field to carry it into `workflow.yaml` | Dashed connector, no arrows |
| **Moment and data** | Annotation with two fixed lines: `Moment: …` and `Data: …` | Dashed connector, no arrows |

Rules this pattern relies on:

- Everything sits inside the process section and inside the lane of the role doing the action (R6).
- Links to a system, document, data store or annotation are dashed; a solid one is rejected (R3).
- A system, document or annotation not linked to any step is flagged (W5); being *near* a step isn't a link.
- Use the annotation, not loose text or a sticky note: the annotation is exported and travels with the step (W3, W4).
- The minimum is action + system + annotation; leave out the document when there isn't one.

On export, line breaks inside the annotation are folded into one line; the `Moment:` and `Data:` prefixes keep the two parts separable for code and AI.

| Board | Covers |
|---|---|
| `QA-003-activity-pattern.board.json` | Start, two activities with the full and the minimal pattern, end; system, document and annotation associations |
