# Library self-test

Three FigJam sections, extracted to `board.json`, that together use **every published component** of the
*Process Design Standards/Components* library (v1.0) and the native-connector rules. `tooling/selftest.py`
runs them through the intake rules; all three must pass with 0 errors and 0 warnings. Run it after any change to
the library, `tooling/workflow_core.py` or `schemas/workflow.schema.json`.

| Board | Section | Covers |
|---|---|---|
| `QA-001-es.board.json` | [QA-001 Prueba de componentes (ES)](https://www.figma.com/board/<selftest-file-key>/?node-id=3-164) | All Spanish components, to-be markers (changed, removed), off-page link, AND, intermediate event, all four data/annotation shapes |
| `QA-002-en.board.json` | [QA-002 Component self-test (EN)](https://www.figma.com/board/<selftest-file-key>/?node-id=3-302) | All English components, as-is pain-point marker (label read from the nested step) |
| `P2P-03-template.board.json` | [Process template → Worked example](https://www.figma.com/board/<template-file-key>/?node-id=2-131) | The template's worked example: external lane, dashed handoff, dotted associations, `Approved` header (validated path) |

The four retired arrow components (`_Conectores/*`, `_Connectors/*`) are hidden from the library; a board that still
uses one fails intake with rule R2 and a fix message.

`selftest.py` also builds broken copies on the fly, so every newer rule is proven to fire: a default label, lane role
or header field left in place (R9), a decision that isn't a question (W7), more than 15 activities (W8), and a
well-formed and a broken process inventory workbook (I1–I8, see `tooling/inventory_check.py`).
