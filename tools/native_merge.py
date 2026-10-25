"""Union native shard observations and check structural coverage explicitly."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from enumerate_combinations import FAMILIES, write_json
from native_backend import build, generate_batch
from tools.native_census import connect, dump, export


def merge(inputs, output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Merge output exists; choose a new directory')
    roots = [Path(p).resolve() for p in inputs]
    if not roots or len(set(roots)) != len(roots):
        raise ValueError('Select distinct native input directories')
    identities = []
    configurations = []
    progress_rows = []
    for path in roots:
        if not (path/'census.sqlite3').is_file():
            raise ValueError('Missing native database: '+str(path))
        with sqlite3.connect((path/'census.sqlite3').as_uri()+'?mode=ro', uri=True) as conn:
            metadata = dict(conn.execute('SELECT name,value FROM metadata'))
            identity = json.loads(metadata['identity'])
            if metadata.get('kind') == 'merged':
                raise ValueError('Merge original shards, not previously merged outputs')
            config = identity['config']
            comparable = {k:v for k,v in config.items() if k not in ('families','left_begin','left_end')}
            identities.append((identity['fingerprint'], comparable))
            configurations.append(config)
            progress_rows.append(conn.execute('SELECT * FROM progress').fetchall())
    if any(row != identities[0] for row in identities):
        raise ValueError('Native shard source/config mismatch')
    output.mkdir(parents=True, exist_ok=True)
    destination = connect(output/'census.sqlite3')
    with destination:
        destination.execute('INSERT INTO metadata VALUES (?,?)', ('identity', dump({
            'fingerprint': identities[0][0], 'config': identities[0][1]})))
        destination.execute('INSERT INTO metadata VALUES (?,?)', ('kind','merged'))
        for path in roots:
            with sqlite3.connect((path/'census.sqlite3').as_uri()+'?mode=ro', uri=True) as source:
                destination.executemany('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',
                                        source.execute('SELECT * FROM observations'))
    shared = identities[0][1]
    with tempfile.TemporaryDirectory(prefix='mcr-merge-') as tmp:
        info = generate_batch(build(), Path(tmp)/'probe.bin', family='standard',
                              tiles=shared['tiles'], max_records=1,
                              include_melds=shared['include_melds'])
    pair_count = info['pairs']
    complete = {f: False for f in FAMILIES}
    intervals = []
    for config, progress in zip(configurations, progress_rows):
        for family, cursor, done in progress:
            if not done:
                continue
            if family == 'standard':
                intervals.append((config['left_begin'], pair_count if config['left_end'] is None
                                  else min(config['left_end'], pair_count)))
            else:
                complete[family] = True
    frontier = 0
    for begin, end in sorted(intervals):
        if begin > frontier:
            break
        frontier = max(frontier, end)
    complete['standard'] = bool(intervals) and frontier >= pair_count
    counts = {p: destination.execute('SELECT COUNT(DISTINCT key) FROM observations WHERE policy=?',
                                     (p,)).fetchone()[0] for p in ('all_optimal','canonical')}
    distribution = dict(destination.execute(
        "SELECT total,COUNT(DISTINCT key) FROM observations WHERE policy='all_optimal' GROUP BY total"))
    scope_complete = all(complete.values())
    summary = {'backend':'native-cpu-merged-v1','inputs':[str(p) for p in roots],
               'source_sha256': identities[0][0], 'config': shared, 'families_complete':complete,
               'standard_pair_count':pair_count, 'standard_intervals':intervals,
               'scope_complete':scope_complete, 'complete':scope_complete
               and shared['tiles'] == list(range(34)) and shared['include_melds']
               and shared['min_fan'] == 8 and shared['max_fan'] is None,
               'combination_count':counts['all_optimal'],'canonical_count':counts['canonical'],
               'fan_distribution':distribution,
               'observation_count':destination.execute('SELECT COUNT(*) FROM observations').fetchone()[0],
               'note':'set union of category observations; merged output is not a resumable search checkpoint'}
    export(destination, output)
    write_json(output/'summary.json', summary)
    destination.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    destination.close()
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('inputs', nargs='+')
    p.add_argument('--output', required=True)
    a = p.parse_args()
    print(json.dumps(merge(a.inputs, a.output), ensure_ascii=False, indent=2))
