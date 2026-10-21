"""Safety net for moving modules around (docs/roadmap.md, phase 2): cogs have no
tests of their own, so a broken import or a forgotten extension would otherwise
show up only when the bot starts in production."""

import importlib
import inspect
from pathlib import Path

import pytest

import main

ROOT = Path(__file__).resolve().parents[2]
_SKIPPED_DIRS = {"tests", "venv", ".venv", "__pycache__"}


def _application_modules() -> list[str]:
    modules = []
    for path in sorted(ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT)
        if any(part in _SKIPPED_DIRS or part.startswith(".") for part in relative.parts[:-1]):
            continue
        parts = relative.with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            modules.append(".".join(parts))
    return modules


def _extension_modules() -> set[str]:
    """Modules that define their own `setup` coroutine, plus the packages that
    re-export it (load_extension("cogs.presentation") imports the package)."""
    found = set()
    for name in _application_modules():
        setup = getattr(importlib.import_module(name), "setup", None)
        if inspect.iscoroutinefunction(setup):
            found.add(name)
    # A package re-exporting its submodule's setup is the extension; the
    # submodule itself is not loaded on its own.
    return {name for name in found if name.rsplit(".", 1)[0] not in found}


@pytest.mark.parametrize("module", _application_modules())
def test_every_application_module_imports(module):
    importlib.import_module(module)


def test_every_extension_is_listed_in_main():
    listed = set(getattr(main, "EXTENSIONS", []))
    assert _extension_modules() == listed


def test_disabled_extensions_are_listed_extensions():
    assert set(main.DISABLED_COGS) <= set(getattr(main, "EXTENSIONS", []))
