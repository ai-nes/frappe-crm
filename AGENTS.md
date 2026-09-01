# Repository Guidelines

## Project Structure & Module Organization

Frappe CRM is a Frappe app with a Python backend and Vue/Vite frontend. Backend code, DocTypes, APIs, migrations, fixtures, and translations live under `crm/`; Python tests are in `crm/tests/`, with demo/seed contract tests in `crm/demo/`. Frontend source is in `frontend/src/`, unit tests in `frontend/tests/unit/`, and Playwright tests in `frontend/tests/e2e/`. Use `scripts/` for utilities, `docker/` for containers, `.github/workflows/` for CI, and `docs/` for documentation.

## Build, Test, and Development Commands

- `task setup` starts the development Frappe stack and installs frontend dependencies.
- `task up` / `task down` starts or stops Docker; `task fe` runs Vite on port 5000.
- `task migrate` validates DocType JSON and runs site migrations; use `task restart` after backend changes when needed.
- `cd frontend && yarn build` builds production frontend assets; `yarn test:run` runs Vitest once.
- `cd frontend && yarn test:coverage` runs Vitest with coverage; `yarn test:e2e` runs Playwright.
- In a prepared Bench environment, run `bench --site <site> run-tests --app crm` for server tests.
- Run `ruff check .` and `ruff format --check .` for Python lint and formatting checks.

## Coding Style & Naming Conventions

Follow the existing Vue/JavaScript style and run ESLint and Oxlint before submitting; Prettier handles frontend formatting. Python targets 3.10+, uses Ruff, a 110-character line length, double quotes, and tab indentation from `pyproject.toml`. Use `snake_case` for Python and camelCase for JavaScript; keep DocType and field names consistent with the schema.

## Testing Guidelines

Name Vitest files `*.test.js` and Playwright files `*.spec.ts`. Add focused tests for utility, business-rule, user-flow, and permission changes. Preserve or improve coverage; CI runs frontend coverage and Bench server tests.

## Commit & Pull Request Guidelines

Use Conventional Commits, for example `feat(admissions): add intake validation` or `fix(report): handle missing table`. Keep commits focused. Pull requests should explain the behavior change, link the issue or task, describe test commands/results, and include screenshots or recordings for visible UI changes. Call out migrations, seed-data changes, configuration requirements, and any backward-compatibility impact.

## Security & Configuration Tips

Never commit credentials, tokens, or local environment files. Keep secrets and site settings in the local environment. Treat seed/reset commands carefully: `task seed-fresh` and `task reset` can destroy local database data.
