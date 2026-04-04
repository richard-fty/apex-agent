MODEL ?=
STRATEGY ?= truncate
POLICY ?= default
BUDGET ?=
PROMPT ?=

.PHONY: tui chat ask

tui:
	uv run python -m tui.app $(if $(MODEL),--model $(MODEL),) --strategy $(STRATEGY) --policy $(POLICY) $(if $(BUDGET),--budget $(BUDGET),)

chat: tui

ask:
	uv run python main.py $(if $(MODEL),--model $(MODEL),) --strategy $(STRATEGY) --policy $(POLICY) $(if $(BUDGET),--budget $(BUDGET),) "$(PROMPT)"
