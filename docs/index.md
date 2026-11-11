# Process documentation

Generated from the repository, never edited by hand:

- **Processes**: one page per validated workflow, written by `tooling/workflow_intake.py` into `docs/processes/<area>/`.
- **Procedures**: one guide per task done in a system, with numbered steps, screenshots and a narrated video in Spanish and English, written by `tooling/procedure_render.py` into `docs/procedures/<area>/`. Each guide carries the result of its last QA run against the system.

Add each new page to `nav` in `mkdocs.yml`.
