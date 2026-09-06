# Same gates as CI. Usage: make install | make lint | make type | make test | make all
PY ?= python

.PHONY: install lint format type test all clean results stack

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

all: lint type test

# Regenerates docs/RESULTS.md inputs (CPU stage: demo traffic, monitor self-evaluation, regression
# gates, canary, replay, incident report; the HF stage needs a GPU and MODEL=...).
results:
	bash scripts/run_experiments.sh

# Collector + Prometheus + Grafana (needs Docker); see deploy/docker-compose.yml.
stack:
	docker compose -f deploy/docker-compose.yml up --build

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
