# Repository Guidelines

## Project Structure & Module Organization

`src/agent_mailer/` contains the FastAPI application. Route handlers live in `src/agent_mailer/routes/`, shared database/auth/config helpers sit beside `main.py`, and the browser console assets are in `src/agent_mailer/static/` (`js/`, `styles.css`, SEO text files, and images). Tests are in `tests/` and mirror the main API areas, such as `test_messages.py`, `test_agents.py`, and `test_admin.py`. Project documentation and screenshots live in `README.md`, `README_CN.md`, `SETUP.md`, and `docs/`.

## Build, Test, and Development Commands

- `uv sync` installs runtime and development dependencies from `pyproject.toml` and `uv.lock`.
- `./run.sh` starts the local broker on port `9800` using `uvicorn`.
- `uv run uvicorn agent_mailer.main:app --port 9800` is the explicit local server command.
- `uv run pytest tests/ -v` runs the full test suite.
- `uv run pytest tests/test_messages.py -v` runs a focused test module.
- `AGENT_MAILER_SECRET_KEY=change-this-secret docker compose up -d` starts the production-like PostgreSQL stack.

## Coding Style & Naming Conventions

Use Python 3.11+ with 4-space indentation and type hints where they clarify API contracts. Keep FastAPI route modules grouped by resource (`messages`, `agents`, `teams`, etc.) and prefer async handlers/helpers when they touch the database. Name Python files and functions with `snake_case`; use concise, resource-oriented route function names. Static UI code is plain JavaScript and CSS, so keep browser changes dependency-free unless a frontend build step is intentionally introduced.

## Testing Guidelines

The suite uses `pytest`, `pytest-asyncio`, and `httpx`; `asyncio_mode = "auto"` is configured in `pyproject.toml`. Add or update tests with each behavior change, especially for auth, multitenancy, message threading, file handling, and admin routes. Use `test_<behavior>` function names and keep fixtures in `tests/conftest.py` or the relevant test module.

## Commit & Pull Request Guidelines

Recent history uses short imperative subjects, sometimes with conventional prefixes such as `feat:` and `docs:`. Prefer examples like `Add team memory search` or `docs: Update setup guide`. PRs should include a brief summary, test results (`uv run pytest tests/ -v` or focused equivalent), linked issues when applicable, and screenshots for changes under `src/agent_mailer/static/` or `docs/`.

## Security & Configuration Tips

Never commit real `.env` files, API keys, JWT secrets, upload data, or database files. Local development defaults to SQLite; Docker Compose uses PostgreSQL and requires `AGENT_MAILER_SECRET_KEY`. Treat generated agent identity files as credentials when they contain broker URLs, addresses, or API usage instructions.
