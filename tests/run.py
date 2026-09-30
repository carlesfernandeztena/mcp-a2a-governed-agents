"""Run every test module: uv run python -m tests.run"""
import importlib
import pkgutil
from pathlib import Path

failed = 0
for mod in sorted(m.name for m in pkgutil.iter_modules([str(Path(__file__).parent)]) if m.name.startswith("test_")):
    module = importlib.import_module(f"tests.{mod}")
    for name in [n for n in dir(module) if n.startswith("test_")]:
        try:
            getattr(module, name)()
            print(f"ok   {mod}.{name}")
        except Exception as e:  # report every failure, then exit non-zero
            failed += 1
            print(f"FAIL {mod}.{name}: {e!r}")
raise SystemExit(1 if failed else 0)
