.PHONY: lint test check-indices ci

lint:
	python -m ruff check src/ api/ tests/ || true
	python -m mypy src/ api/ --ignore-missing-imports || true

check-indices:
	python scripts/check_hardcoded_indices.py src/validators/

test:
	pytest tests/ -q --tb=short

ci: lint check-indices test
