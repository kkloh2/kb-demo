# Data Hub (prototype)

A generative-BI workspace prototype modelled on Amazon Quick (chat agents, dashboards,
research, flows), built on the OCBC-themed common platform.

| Layer    | Stack                                  | Path        |
|----------|----------------------------------------|-------------|
| Frontend | React 18 + TypeScript + Vite           | `frontend/` |
| Backend  | Python 3.13 + FastAPI + SQLite         | `backend/`  |
| Design   | Screenshots of the running app         | `design/`   |

## Design screenshots

`design/` holds screenshots of each page, captured from the running app at 1440×900.

## Run locally

```bash
# Backend: http://localhost:8000  (docs at /docs)
cd backend
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest -q

# Frontend: http://localhost:5173  (proxies /api to :8000)
# Node 26.13.0 (npm 11.20.0) comes from a mamba env. Pick the spec file for your platform:
#   Linux x86-64:           requirements-frontend-linux-64.txt
#   macOS (Apple Silicon):  requirements-frontend.txt
mamba create -n frontend-env -c conda-forge --file requirements-frontend-linux-64.txt   # once
mamba activate frontend-env
cd frontend
npm ci
npm run dev
```

The backend creates and seeds a SQLite database at `backend/data/datahub.db` on first start.
Reset it with `cd backend && .venv/bin/python -m app.db.reset`.

Demo accounts (all in [docs/auth-module.md](docs/auth-module.md#11-demo-accounts)):

| LAN ID | Password | Role |
|---|---|---|
| `admin` | `admin123` | System admin |
| `analyst` | `datahub123` | Risk viewer, with HR Policies shared |
| `risk.admin` / `risk.maker` / `risk.checker` | `demo123` | Risk department admin / maker / checker |

## Documentation

- [Auth module and access control](docs/auth-module.md): roles, permissions, token, database schema, API, security controls.
- [Approval workflow module](docs/approval-workflow.md): design, tables, API, and the plan for SpiffWorkflow-driven flows from uploaded BPMN files.

## Theming

All brand values live in `frontend/src/styles/tokens.css`. Components use semantic tokens
(`--text-primary`, `--brand-red` and so on) only. The logo is `frontend/public/ocbc-logo.svg`.
