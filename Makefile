PYTHON ?= .venv/bin/python
SITE_DIR ?= frontend/dist
# The CDK CLI pinned in package-lock.json (`make install` runs npm ci).
CDK ?= npx --no-install cdk

.PHONY: install check lint test audit frontend privacy lock synth diff clean

install:            ## Create the virtualenv and install everything (uv if installed, else pip)
	if command -v uv >/dev/null; then \
		uv venv --seed --allow-existing --python python3.14 .venv && uv pip install --python $(PYTHON) --require-hashes -r requirements-dev.txt && uv pip check --python $(PYTHON); \
	else \
		python3.14 -m venv .venv && $(PYTHON) -m pip install --upgrade pip && $(PYTHON) -m pip install --require-hashes -r requirements-dev.txt && $(PYTHON) -m pip check; \
	fi
	npm ci --ignore-scripts --no-audit --no-fund  # the CDK CLI and pyright
	npm ci --prefix frontend --ignore-scripts --no-audit --no-fund  # the PWA and its tools

check:              ## Everything CI checks, locally (synth uses a stand-in app, like CI)
	$(MAKE) privacy lint test frontend audit
	$(MAKE) synth SITE_DIR=tests/fixtures/site

lint:               ## Python: ruff (with Bandit security rules) and pyright types
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	npx --no-install pyright

test:
	$(PYTHON) -m pytest -n auto

audit:              ## Check dependencies for known vulnerabilities
	$(PYTHON) -m pip_audit --require-hashes --disable-pip -r requirements-dev.txt

frontend:           ## PWA: ESLint, TypeScript types, Vitest, Vite build and the size limit
	cd frontend && npm run -s lint && npm run -s typecheck && npm run -s test && npm run -s build
	scripts/check_size.sh frontend/dist

privacy:            ## Fail on emails, AWS account IDs or data exports in tracked files
	scripts/check_personal_data.sh

lock:               ## Regenerate the hashed lockfiles from the .in files
	for d in requirements requirements-dev; do $(PYTHON) -m piptools compile --quiet --generate-hashes --allow-unsafe \
		--strip-extras --no-emit-index-url --output-file=$$d.txt $$d.in; done

synth:              ## Synthesize CloudFormation and run cdk-nag security checks
	. .venv/bin/activate && $(CDK) synth --quiet -c siteDir=$(SITE_DIR)

diff:
	. .venv/bin/activate && $(CDK) diff

clean:
	rm -rf build cdk.out .pytest_cache .ruff_cache .coverage
