# SIPL Debugger extension

This VS Code extension provides `.sipl` syntax highlighting and a Debug Adapter
Protocol client for the Python SIPL Toolkit. The language implementation stays
in the shared Python package; the extension only launches its adapter.

1. Install the toolkit in the workspace Python environment:
   `python3 -m pip install -e .`
2. Open this project in VS Code and install/package this extension.
3. Open an `.sipl` program, set breakpoints, press F5, and select
   **Debug SIPL program**.
4. Set `sipl.pythonPath` if the package is installed under a different Python
   executable.

The debugger supports source-line breakpoints, continue, step, variables, and
integer arithmetic expression evaluation. Its execution limit is configurable
with `maxSteps`.

