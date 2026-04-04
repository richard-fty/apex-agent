"""Textual CSS styles for the Relay TUI."""

APP_CSS = """
Screen {
    layout: grid;
    grid-size: 2 3;
    grid-columns: 2fr 1fr;
    grid-rows: auto 1fr auto;
}

#header {
    column-span: 2;
    height: 3;
    background: $primary-background;
    color: $text;
    content-align: center middle;
    text-style: bold;
    padding: 0 2;
}

#agent-output {
    row-span: 1;
    border: solid $primary;
    border-title-color: $success;
    overflow-y: auto;
    padding: 1 2;
}

#sidebar {
    row-span: 1;
    layout: vertical;
}

#tool-trace {
    border: solid $secondary;
    border-title-color: $warning;
    height: 2fr;
    overflow-y: auto;
    padding: 0 1;
}

#metrics-panel {
    border: solid $accent;
    border-title-color: $accent;
    height: 1fr;
    padding: 0 1;
}

#input-area {
    column-span: 2;
    height: auto;
    max-height: 5;
    dock: bottom;
}

#prompt-input {
    margin: 0 1;
}

#status-bar {
    column-span: 2;
    height: 1;
    background: $primary-background;
    color: $text-muted;
    padding: 0 2;
    dock: bottom;
}

.tool-success {
    color: $success;
}

.tool-error {
    color: $error;
}

.tool-running {
    color: $warning;
}

.dim-text {
    color: $text-muted;
}

.metric-label {
    color: $text-muted;
    width: 14;
}

.metric-value {
    color: $text;
    text-style: bold;
}
"""
