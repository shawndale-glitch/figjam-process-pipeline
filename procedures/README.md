# Procedures

One `procedure.yaml` per task done in a system, in `procedures/<area>/<procedure_id>/`. Each one is tied to a process in `workflows/`: `process` is the process ID, `role` a lane on it and `step_ref` the step it carries out.

| ID | Task | Role | Starts from |
|---|---|---|---|
| [P2P-03-P01](procure-to-pay/P2P-03-P01/procedure.yaml) | Open an invoice | AP Clerk | |
| [P2P-03-P02](procure-to-pay/P2P-03-P02/procedure.yaml) | Add an internal note to an invoice | AP Clerk | P2P-03-P01 |
| [P2P-03-P03](procure-to-pay/P2P-03-P03/procedure.yaml) | Assign the cost centre | AP Clerk | P2P-03-P01 |
| [P2P-03-P04](procure-to-pay/P2P-03-P04/procedure.yaml) | Approve an invoice | Finance Manager | P2P-03-P01 |

- Contract: [`schemas/procedure.schema.json`](../schemas/procedure.schema.json). Rules: [`governance/workflow-rules.yaml`](../governance/workflow-rules.yaml) → `procedure` (P1–P9, PW1–PW2).
- Check: `python tooling/procedure_check.py`. Record: `python tooling/procedure_run.py <procedure.yaml> --start-demo`. Render: `python tooling/procedure_render.py --all`.
- Guides land in [`docs/procedures/`](../docs/procedures/index.md).

Writing one: start from the user's point of view. Every `say` is what you'd tell a colleague, every `do` names the control by what's on screen (role and name, label, text), and every step has an `expect` that proves it worked. Keep it under 12 steps; move a shared opening into its own procedure and point to it with `starts_from`.
