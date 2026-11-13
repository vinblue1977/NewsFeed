# Working in this repo

Personal, iPhone-first news PWA: Preact + Vite + TypeScript frontend, Python ingest Lambdas (EventBridge schedule -> S3 JSON), CloudFront, AWS CDK. No login, no API Lambda, no user table. Cost target: under $0.15/month. Plan and decisions: `PLAN.md`.

## Layout

- `frontend/` Preact PWA (`npm` scripts: lint, typecheck, test, build). Gzipped JS+CSS budget: 150 KB (`scripts/check_size.sh`).
- `backend/ingest/` ingest Lambda code. Tests import it as `ingest.*`.
- `infra/` CDK stack, `app.py` entry point. cdk-nag (AwsSolutions) runs on every synth; each suppression needs a reason.
- `scripts/` privacy guard and size check. `tests/` pytest (coverage floor 90%).
- Dependencies: `requirements.in` -> hashed `requirements.txt` via `make lock`. Never hand-edit the `.txt` files.

## Commands

- `make install` sets up `.venv` and node tools. `make check` is everything CI runs (privacy, lint, test, frontend, audit, synth). Run it before pushing.

## Pull requests

- Branch from an up-to-date `main`; never commit to `main` directly.
- Conventional PR title (`feat:`, `fix:`, `ci:`, `docs:`, `chore:`...); PRs are squash-merged and the title becomes the commit.
- Keep the repo free of personal data: no emails, no AWS account IDs, no data exports (`make privacy` enforces this). Use placeholders.
- Do not deploy from a laptop; deploys go through CI once a deploy job exists.
- Dependabot PRs auto-merge via `dependabot-automerge.yml` (needs the `AUTOMERGE_TOKEN` secret). Never `gh pr update-branch` a Dependabot PR; comment `@dependabot rebase` instead.
