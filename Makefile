.PHONY: test lint test-unit test-integration format

test-unit:
	python -m pytest tests/ -v --ignore=tests/test_integration.py

test-integration:
	python -m pytest tests/test_integration.py -v

test:
	python -m pytest tests/ -v --cov=src/pdo --cov-report=term-missing

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff format src/ tests/
