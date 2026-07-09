# ATMS Project Makefile
# Panel product: services/panel-gateway + panel/ (Tauri app)

.PHONY: help test lint format typecheck clean structure install-service \
        run-service test-service \
        secrets-decrypt secrets-encrypt secrets-edit secrets-rotate-recipients \
        secrets-check

# Colors
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

help:
	@echo "$(BLUE)╔════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║     ATMS Project - Available Commands                 ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(GREEN)Setup Commands:$(NC)"
	@echo "  make install-service    - Install service dependencies (SERVICE=name)"
	@echo ""
	@echo "$(GREEN)Development:$(NC)"
	@echo "  make run-service       - Run a specific service (SERVICE=name)"
	@echo ""
	@echo "$(GREEN)Testing:$(NC)"
	@echo "  make test              - Run all test suites (panel-gateway, decision-engine, traffic-controller)"
	@echo "  make test-service      - Run tests for specific service (SERVICE=name)"
	@echo ""
	@echo "$(GREEN)Code Quality:$(NC)"
	@echo "  make lint              - Run linters"
	@echo "  make format            - Format code"
	@echo "  make typecheck         - Run type checking"
	@echo ""
	@echo "$(GREEN)Utilities:$(NC)"
	@echo "  make clean             - Clean temporary files"
	@echo "  make structure         - Show project structure"
	@echo ""
	@echo "$(GREEN)Secrets (Phase A5):$(NC)"
	@echo "  make secrets-decrypt ENV=dev               - Decrypt deploy/secrets/$$ENV/atms.env.sops → .env"
	@echo "  make secrets-edit ENV=dev FILE=...sops     - Edit a SOPS file in place"
	@echo "  make secrets-encrypt ENV=dev FILE=...      - Encrypt a plaintext file"
	@echo "  make secrets-rotate-recipients             - Re-encrypt after .sops.yaml change"
	@echo "  make secrets-check                         - Verify committed *.sops files look encrypted"
	@echo ""

install-service:
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(YELLOW)Usage: make install-service SERVICE=panel-gateway$(NC)"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Installing dependencies for $(SERVICE)...$(NC)"
	@cd services/$(SERVICE) && \
		python3.11 -m venv venv && \
		. venv/bin/activate && \
		pip install -r requirements.txt
	@echo "$(GREEN)✓ $(SERVICE) dependencies installed$(NC)"

run-service:
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(YELLOW)Usage: make run-service SERVICE=panel-gateway$(NC)"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Running $(SERVICE) service...$(NC)"
	@cd services/$(SERVICE) && \
		. venv/bin/activate && \
		cd src && \
		python main.py

test:
	@echo "$(YELLOW)Running all test suites...$(NC)"
	@cd services/panel-gateway && pytest tests/ -q
	@cd services/decision-engine && pytest tests/ -q
	@cd services/traffic-controller && pytest tests/ -q

test-service:
	@if [ -z "$(SERVICE)" ]; then \
		echo "$(YELLOW)Usage: make test-service SERVICE=panel-gateway$(NC)"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Testing $(SERVICE) service...$(NC)"
	@cd services/$(SERVICE) && \
		. venv/bin/activate && \
		pytest tests/ -v

lint:
	@echo "$(YELLOW)Running linters...$(NC)"
	@ruff check services/ shared/ || true
	@echo "$(GREEN)✓ Linting complete$(NC)"

format:
	@echo "$(YELLOW)Formatting code...$(NC)"
	@black services/ shared/ || true
	@ruff check --fix services/ shared/ || true
	@echo "$(GREEN)✓ Code formatted$(NC)"

typecheck:
	@echo "$(YELLOW)Running type checks...$(NC)"
	@mypy services/ shared/ || true
	@echo "$(GREEN)✓ Type checking complete$(NC)"

clean:
	@echo "$(YELLOW)Cleaning temporary files...$(NC)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

structure:
	@echo "$(BLUE)ATMS Project Structure:$(NC)"
	@tree -L 3 -I '__pycache__|*.pyc|venv|.git|htmlcov|.pytest_cache|.mypy_cache|.ruff_cache' . 2>/dev/null || \
		find . -type d -not -path '*/\.*' -not -path '*/venv/*' -not -path '*/__pycache__/*' | sort | head -50

# ---------------------------------------------------------------------------
# Secrets (Phase A5 — SOPS + age, see docs/adr/0002 and docs/runbooks/secrets.md)
# ---------------------------------------------------------------------------

# Default env when not specified. Set explicitly for staging/prod operations.
ENV ?= dev

# Resolve sops binary; fail loudly if not installed.
SOPS := $(shell command -v sops 2>/dev/null)
AGE  := $(shell command -v age 2>/dev/null)

_secrets_require_tools:
	@if [ -z "$(SOPS)" ]; then echo "$(YELLOW)✗ sops not installed. brew install sops$(NC)"; exit 1; fi
	@if [ -z "$(AGE)" ];  then echo "$(YELLOW)✗ age not installed. brew install age$(NC)";  exit 1; fi

secrets-decrypt: _secrets_require_tools
	@$(eval IN := deploy/secrets/$(ENV)/atms.env.sops)
	@$(eval OUT := .env)
	@if [ ! -f "$(IN)" ]; then echo "$(YELLOW)✗ $(IN) not found$(NC)"; exit 1; fi
	@echo "$(YELLOW)Decrypting $(IN) → $(OUT)$(NC)"
	@$(SOPS) --decrypt "$(IN)" > "$(OUT)"
	@chmod 600 "$(OUT)"
	@echo "$(GREEN)✓ $(OUT) (mode 600) — DO NOT commit$(NC)"

# Edit a SOPS-encrypted file in place. Uses $EDITOR (default: vi).
# Example: make secrets-edit ENV=dev FILE=atms.env.sops
secrets-edit: _secrets_require_tools
	@if [ -z "$(FILE)" ]; then echo "$(YELLOW)Usage: make secrets-edit ENV=dev FILE=atms.env.sops$(NC)"; exit 1; fi
	@$(SOPS) "deploy/secrets/$(ENV)/$(FILE)"

# Encrypt a plaintext file in place, producing $FILE.sops.
# Example: make secrets-encrypt ENV=dev FILE=atms.env
secrets-encrypt: _secrets_require_tools
	@if [ -z "$(FILE)" ]; then echo "$(YELLOW)Usage: make secrets-encrypt ENV=dev FILE=atms.env$(NC)"; exit 1; fi
	@$(eval SRC := deploy/secrets/$(ENV)/$(FILE))
	@$(eval DEST := $(SRC).sops)
	@if [ ! -f "$(SRC)" ]; then echo "$(YELLOW)✗ $(SRC) not found$(NC)"; exit 1; fi
	@$(SOPS) --encrypt --in-place "$(SRC)"
	@mv "$(SRC)" "$(DEST)"
	@echo "$(GREEN)✓ $(DEST) — safe to commit. Plaintext removed.$(NC)"

# Re-encrypt every SOPS file under deploy/secrets/ after a .sops.yaml change
# (added or removed recipient).
secrets-rotate-recipients: _secrets_require_tools
	@echo "$(YELLOW)Re-encrypting every deploy/secrets/**/*.sops with current .sops.yaml ...$(NC)"
	@find deploy/secrets -type f \( -name '*.sops' -o -name '*.sops.env' -o -name '*.sops.yaml' \) | while read f; do \
		echo "  $$f"; \
		$(SOPS) updatekeys --yes "$$f"; \
	done
	@echo "$(GREEN)✓ Rotation complete. Commit the result.$(NC)"

# Lightweight check that runs without sops/age: confirms every committed
# `*.sops*` file under deploy/secrets/ doesn't look like plaintext.
secrets-check:
	@bad=0; \
	for f in $$(find deploy/secrets -type f -name '*.sops*' 2>/dev/null); do \
		if ! head -c 4096 "$$f" | grep -qE '(sops:|ENC\[|age-encryption)' && ! grep -q 'PLACEHOLDER' "$$f"; then \
			echo "$(YELLOW)✗ $$f does not look encrypted$(NC)"; bad=1; \
		fi; \
	done; \
	if [ $$bad -eq 0 ]; then echo "$(GREEN)✓ all secrets files look encrypted (or are explicit placeholders)$(NC)"; fi; \
	exit $$bad
