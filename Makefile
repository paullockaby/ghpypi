# stop on error, no built in rules, run silently
MAKEFLAGS="-S -r -s"

all: build

.PHONY: build
build:
	@echo "Nothing to build. Try 'test' instead."

.PHONY: install
install:
	pre-commit install
	poetry install --no-interaction

.PHONY: test
test: install
	poetry run pytest --mypy --cov=src --cov-report=term --cov-report=html

.PHONY: pre-commit
pre-commit: install
	pre-commit run --all-files

.PHONY: clean
clean:
	rm -rf dist/ .pytest_cache/ .mypy_cache/ .coverage htmlcov/
	find . -type d -name "__pycache__" -print0 | xargs -0 rm -rf
