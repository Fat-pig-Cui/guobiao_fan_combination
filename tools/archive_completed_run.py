"""Archive the superseded 2026-10-21 runs without deleting any files.

Keep final results and a bound coverage audit outside the disposable archive.
Refuse an existing destination, running/incomplete tasks, or changed artifacts.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from enumerate_combinations import write_json
from tools.basis_coverage import sha256, verify_coverage

OLD_DOCUMENTS = (
    'ACCELERATION_PLAN.md', 'BASIS_RUNTIME_ESTIMATE.md', 'CUDA_HAND_SOLVER.md',
    'DESIGN.md', 'HAND_SOLVER.md', 'LOCAL_RUN.md', 'NATIVE_ENUMERATION_PLAN.md',
    'NATIVE_VALIDATION.md', 'THEORY.md', 'VALIDATION.md', 'WINDOWS_CUDA.md',
    'WINDOWS_NATIVE.md', 'WINDOWS_RESUME.md',
)
OLD_RESULTS = (
    'basis-timing-continuous-20261021', 'basis-timing-finish-20261021',
    'basis-timing-pilot-20261021', 'basis-timing-random-a-20261021',
    'basis-timing-random-b-20261021', 'basis-timing-row-inventory-20261021',
    'basis-validation', 'native-local-20261021', 'native-validation',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    destination = args.archive.resolve()
    if destination.parent != ROOT / 'archive' or destination.exists():
        raise ValueError('Choose a new direct child of this project archive directory')
    run = ROOT / 'results/basis-full-local-20261021'
    status = json.loads((run / 'RUN_STATUS.json').read_text())
    plan = json.loads((run / 'tasks.json').read_text())
    coverage = verify_coverage(run, status, plan, require_databases=True)
    saved = json.loads((run / 'coverage-audit.json').read_text())
    assert saved['tasks'] == coverage['tasks'] and saved['passed']
    assert saved['manifest_sha256'] == coverage['manifest_sha256']
    assert saved['status_sha256'] == coverage['status_sha256']
    publication = ROOT / 'reports/basis-full-20261021'
    for row in json.loads((publication / 'artifacts.json').read_text()):
        path = ROOT / row['file']
        assert path.stat().st_size == row['bytes'] and sha256(path) == row['sha256'], path
    destination.mkdir(parents=True)
    # Small source/publication snapshots preserve historical interpretation.
    source = destination / 'source'
    source.mkdir()
    for path in ROOT.glob('*.py'):
        shutil.copy2(path, source / path.name)
    for name in ('tools', 'native', 'cuda', 'tests', 'examples'):
        shutil.copytree(ROOT / name, source / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
    for name in ('requirements.txt', 'LICENSE', '.gitignore'):
        shutil.copy2(ROOT / name, source / name)
    before = destination / 'publication-before-archiving'
    before.mkdir()
    for path in ROOT.glob('*.md'):
        shutil.copy2(path, before / path.name)
    shutil.copy2(run / 'coverage-audit.json', before / 'coverage-audit.json')
    moves = []

    def move(path, target):
        if not path.exists():
            raise ValueError('Expected historical artifact is missing: ' + str(path))
        if target.exists():
            raise ValueError('Archive collision: ' + str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        moves.append({'original': str(path.relative_to(ROOT)),
                      'archived': str(target.relative_to(ROOT))})

    for name in OLD_DOCUMENTS:
        move(ROOT / name, destination / 'documents' / name)
    for name in OLD_RESULTS:
        move(ROOT / 'results' / name, destination / 'results' / name)
    intermediates = destination / 'run-intermediates' / run.name
    for name in ('tasks', 'requests', 'controller.lock'):
        move(run / name, intermediates / name)
    for path in sorted(run.glob('*.log')):
        move(path, intermediates / path.name)
    move(publication, before / 'report-data')
    if (ROOT / 'tmp').exists():
        move(ROOT / 'tmp', destination / 'drafts')
    # Build products and live source remain in place for normal reuse.
    write_json(destination / 'MOVES.json', {
        'created_at': datetime.now(timezone.utc).isoformat(), 'moves': moves,
        'deletable': True, 'retained_run': str(run.relative_to(ROOT)),
        'boundary': 'No files deleted. Removing archive loses old checkpoints and benchmarks, not final results.'})
    # Demonstrate that reporting now works from retained evidence alone.
    after = verify_coverage(run, status, plan)
    assert after['verification_mode'] == 'retained_checkpoint_metadata'
    assert after['tasks'] == coverage['tasks']
    print(json.dumps({'archive': str(destination), 'moves': len(moves),
                      'coverage': after['verification_mode'], 'files_deleted': 0}))


if __name__ == '__main__':
    main()
