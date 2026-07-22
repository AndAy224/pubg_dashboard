"""Test package.

This file is not ceremonial: with `tests/` a package, pytest's default
"prepend" import mode puts `backend/` (the first parent *without* an
`__init__.py`) on `sys.path` instead of `backend/tests/`, so
`import pubg_dashboard` resolves even when the project has not been
`uv sync`'d into the environment.
"""

from __future__ import annotations
