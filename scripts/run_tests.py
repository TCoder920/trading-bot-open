import os, sys
from pathlib import Path
import pytest
os.chdir(Path(__file__).resolve().parents[1])
sys.path.insert(0, str(Path.cwd()))
for key in list(os.environ):
    if key.startswith(("ALPACA_", "TRADING_")):
        os.environ.pop(key)
raise SystemExit(pytest.main(["tests/test_custom", "-q"] + sys.argv[1:]))
