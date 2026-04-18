MODEL    ?=
STRATEGY ?= truncate
POLICY   ?= unrestricted
BUDGET   ?=

.PHONY: tui console tui-dev

# Standard launch.
tui:
	cd .. && uv run python -m tui.app $(if $(MODEL),--model $(MODEL),) --strategy $(STRATEGY) --policy $(POLICY) $(if $(BUDGET),--budget $(BUDGET),)

# Terminal 1: Textual devtools console — streams logs from the TUI.
console:
	cd .. && uv run textual console

# Terminal 2: TUI in dev mode, connected to the console listening on :8081.
# APEX_DEBUG=1 flips logging.basicConfig to DEBUG inside tui/app.py.
tui-dev:
	cd .. && APEX_DEBUG=1 TEXTUAL=devtools,debug uv run python -m tui.app $(if $(MODEL),--model $(MODEL),) --strategy $(STRATEGY) --policy $(POLICY) $(if $(BUDGET),--budget $(BUDGET),)
