# Paydesk (procedure demo app)

A small, fictional accounts-payable app that the example procedures are recorded against. It stands in for a real system so the whole pipeline runs from this repository: screens in Spanish and English (`?lang=es|en`) and a JSON API that the runner uses to create test invoices, check what changed and delete them again. Data lives in memory; every supplier is fictional.

```bash
python examples/procedure-demo/app/server.py              # http://127.0.0.1:8765
python examples/procedure-demo/app/server.py --drift      # "Approve" renamed, as after a vendor release
```

`tooling/procedure_run.py --start-demo` starts it for you. With `--drift`, procedure P2P-03-P04 fails at the step that uses the renamed button, which is what CI's `drift` job checks.

| API | Used for |
|---|---|
| `POST /api/invoices` | fixtures: a fictional invoice before a run |
| `GET /api/invoices/<number>` | `verify`: what the run changed (status, cost centre, notes) |
| `DELETE /api/invoices/<number>` | cleanup after the run |
| `GET /api/version` | the app version stamped on the QA report |
