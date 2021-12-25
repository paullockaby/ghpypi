# stop on error, no built in rules, run silently
MAKEFLAGS="-S -r -s"

all: build

.PHONY: build
build:
	@echo "Nothing to build. Try 'test' instead."

.PHONY: test
test:
	poetry install --no-interaction
	poetry run pytest

.PHONY: clean
clean:
	rm -rf dist/
	rm -rf .pytest_cache/
	find . -type d -name "__pycache__" -print0 | xargs -0 rm -rf
