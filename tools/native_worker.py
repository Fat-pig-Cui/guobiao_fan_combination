"""Run an unchanged census with a cooperative pause file on macOS/Windows."""
import _thread
import argparse
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pause-file',type=Path,required=True)
    args,remaining = parser.parse_known_args()
    if remaining[:1] == ['--']:
        remaining = remaining[1:]
    # Import before enabling interruption so normal census cleanup is already
    # available. No Windows console attachment or CTRL_BREAK event is needed.
    from tools.native_census import main as census_main
    from tools.native_parallel import controller_lock
    done = threading.Event()
    def watch():
        while not done.wait(0.2):
            if args.pause_file.exists():
                _thread.interrupt_main()
                return
    threading.Thread(target=watch,daemon=True).start()
    sys.argv = [str(ROOT/'tools/native_census.py'),*remaining]
    output = Path(remaining[remaining.index('--output')+1]).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with controller_lock(output.parent/(output.name+'.worker.lock')):
            return census_main()
    finally:
        done.set()


if __name__ == '__main__':
    raise SystemExit(main())
