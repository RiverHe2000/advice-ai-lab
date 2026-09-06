# Same gates as CI. Usage: make install | make lint | make type | make test | make all
PY ?= python

.PHONY: install lint format type test test-e2e all clean results

install:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

type:
	mypy

test:
	pytest

# Browser tests need `playwright install chromium`; REQUIRE_E2E=1 turns a skip into a failure.
test-e2e:
	REQUIRE_E2E=1 pytest -m e2e --no-cov

all: lint type test

# Regenerates docs/RESULTS.md inputs (corpus, verifier self-evaluation, fake-backend strategy
# comparison, pseudonymisation check; the real-model stage needs a GPU).
results:
	bash scripts/run_experiments.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
