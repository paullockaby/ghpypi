# stop on error, no built in rules, run silently
MAKEFLAGS="-S -r -s"

all: build

.PHONY: build
build:
	@echo "Nothing to build. Try 'test' instead."

.PHONY: install
install:
	poetry install --no-interaction

.PHONY: lint
lint: install
	poetry run pre-commit run --all-files

.PHONY: test
test: install
	poetry run pytest --cov=src --cov-report=term --cov-report=html

.PHONY: clean
clean:
	rm -rf dist/ .pytest_cache/ .mypy_cache/ .coverage htmlcov/
	find . -type d -name "__pycache__" -print0 | xargs -0 rm -rf

.PHONY: pre-commit
pre-commit:
	pre-commit install

.PHONY: bump-check
bump-check:
	cz bump --changelog --dry-run
