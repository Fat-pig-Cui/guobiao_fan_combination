"""Run the existing band census with optional CPU memoization installed."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fast_runtime import install, tune_blocking, tune_solver  # noqa: E402

install()
tune_solver()
tune_blocking()
runpy.run_path(str(ROOT / 'tools' / 'band_census.py'), run_name='__main__')
