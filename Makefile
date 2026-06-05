VENV     := $(HOME)/.venvs/caen
PYTHON   := $(VENV)/bin/python
VENV_BIN := $(VENV)/bin
SITE_PKG := $(shell $(PYTHON) -c "import site; print(site.getsitepackages()[0])")
BUILD    := build-debug
ROOT     := $(abspath .)

.PHONY: all build dev-install clean help

all: build dev-install   ## Build extension + register in venv (default)

build:                   ## (Re)build the pyferslib C++ extension
	cmake --build $(BUILD) --target pyferslib -- -j$$(nproc)

dev-install:             ## Register src/ + build-debug/ in venv; create entry point scripts
	@# A wheel-installed copy in site-packages shadows src/ (it precedes .pth
	@# entries on sys.path), so remove it first and let the .pth point at src/.
	@$(PYTHON) -m pip uninstall -y hydrafers >/dev/null 2>&1 || true
	@printf '%s\n%s\n' '$(ROOT)/src' '$(ROOT)/$(BUILD)' \
		> '$(SITE_PKG)/hydrafers-dev.pth'
	@printf '#!/bin/sh\nexec "$(PYTHON)" -m hydrafers "$$@"\n' \
		> '$(VENV_BIN)/hydrafers'     && chmod +x '$(VENV_BIN)/hydrafers'
	@printf '#!/bin/sh\nexec "$(PYTHON)" -m hydrafers.gui "$$@"\n' \
		> '$(VENV_BIN)/hydrafers-gui' && chmod +x '$(VENV_BIN)/hydrafers-gui'
	@printf '#!/bin/sh\nexec "$(PYTHON)" -m hydrafers.cli tui "$$@"\n' \
		> '$(VENV_BIN)/hydrafers-tui' && chmod +x '$(VENV_BIN)/hydrafers-tui'
	@printf '#!/bin/sh\nexec "$(PYTHON)" -m hydrafers.cli "$$@"\n' \
		> '$(VENV_BIN)/hydrafers-cli' && chmod +x '$(VENV_BIN)/hydrafers-cli'
	@echo ""
	@echo "  hydrafers             launch the Qt GUI (default), or subcommand:"
	@echo "  hydrafers gui         Qt desktop GUI"
	@echo "  hydrafers tui         Textual TUI dashboard"
	@echo "  hydrafers run …       headless acquisition"
	@echo "  hydrafers benchmark … throughput test"
	@echo "  hydrafers-cli         full CLI dispatcher"
	@echo ""
	@echo "Add $(VENV_BIN) to PATH if not already there."

clean:                   ## Remove .pth file and venv scripts
	rm -f '$(SITE_PKG)/hydrafers-dev.pth'
	rm -f '$(VENV_BIN)/hydrafers' '$(VENV_BIN)/hydrafers-gui' \
	      '$(VENV_BIN)/hydrafers-tui' '$(VENV_BIN)/hydrafers-cli'

help:                    ## Show this help
	@grep -E '^[a-zA-Z_-]+:[ ]+##' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":[ ]+##"}{printf "  %-18s %s\n",$$1,$$2}'
