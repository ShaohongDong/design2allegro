PYTHON ?= $(CURDIR)/.venv/bin/python
DEV = PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/dev.py

.PHONY: help build test test-ui example benchmark verify-package clean-preview clean
help:
	@echo "build: one wheel; test: kernel regressions; test-ui: review browser tests; example: Circuit to Telesis"
	@echo "benchmark: 10k physical pins; verify-package: isolated wheel installation"
	@echo "clean-preview/clean: only current parser-generated build outputs"
build test test-ui example benchmark verify-package clean:
	$(DEV) $@
clean-preview:
	$(DEV) clean --dry-run
