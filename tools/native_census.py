"""Transactional, resumable native generation with independent Python scoring.

SQLite is authoritative. JSON summaries/exports are rebuildable views; a crash
cannot commit a cursor without the corresponding physical states and results.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from context_expansion import expand
from decompose import parse
from enumerate_combinations import FAMILIES, write_json
from fast_runtime import install
from native_backend import build, decode, generate_batch, read_batch
from rules import PROFILE

SOURCES = ('rules.py', 'decompose.py', 'reachability.py', 'calc_fan.py',
           'context_expansion.py', 'fast_runtime.py', 'native_backend.py',
           'native/structure_enumerator.cpp', 'tools/native_census.py')


def fingerprint():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=FULL')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS progress (family TEXT PRIMARY KEY, cursor INTEGER NOT NULL,
                                             complete INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS physical (identity BLOB PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS observations (
            key TEXT NOT NULL, policy TEXT NOT NULL, closed INTEGER NOT NULL,
            method TEXT NOT NULL, total INTEGER NOT NULL, evidence TEXT NOT NULL,
            PRIMARY KEY (key, policy, closed, method)) WITHOUT ROWID;
    ''')
    return conn


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def export(conn, output):
    # Export only retained evidence, not every event and not a physical log.
    destination = Path(output)/'combinations.jsonl'
    temporary = destination.with_suffix('.jsonl.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        for key, policy, closed, method, total, evidence in conn.execute(
                'SELECT * FROM observations ORDER BY policy, key, closed, method'):
            row = json.loads(evidence)
            row.update(key=json.loads(key), policy=policy, closed=bool(closed),
                       method=method, total=total)
            stream.write(dump(row)+'\n')
    temporary.replace(destination)


def run(output, *, families=FAMILIES, tiles=tuple(range(34)), include_melds=True,
        left_begin=0, left_end=None, batch_size=1024, max_candidates=0,
        seconds=0, resume=False, export_results=True, min_fan=8, max_fan=None,
        equivalent_winds=True):
    output = Path(output)
    if batch_size < 1 or max_candidates < 0 or seconds < 0:
        raise ValueError('Invalid batch size or run limit')
    if min_fan < 8 or (max_fan is not None and max_fan < min_fan):
        raise ValueError('Invalid eligible fan interval')
    if not families or len(set(families)) != len(families) or set(families)-set(FAMILIES):
        raise ValueError('Invalid family selection')
    tiles = tuple(sorted(set(tiles)))
    if not tiles or any(type(t) is not int or not 0 <= t < 34 for t in tiles):
        raise ValueError('Invalid tile domain')
    if (left_begin or left_end is not None) and tuple(families) != ('standard',):
        raise ValueError('Left-pair shards must use --families standard')
    if left_begin < 0 or (left_end is not None and left_end <= left_begin):
        raise ValueError('Invalid left-pair interval')
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError('Output exists; use --resume or a new directory')
    if resume and not (output/'census.sqlite3').exists():
        raise ValueError('No native checkpoint to resume')
    executable = build()
    install()
    output.mkdir(parents=True, exist_ok=True)
    config = {'families': list(families), 'tiles': list(tiles),
              'include_melds': include_melds, 'left_begin': left_begin, 'left_end': left_end,
              'min_fan': min_fan, 'max_fan': max_fan, 'equivalent_winds': equivalent_winds,
              'profile': PROFILE}
    conn = connect(output/'census.sqlite3')
    expected = {'config': config, 'fingerprint': fingerprint()}
    old = dict(conn.execute('SELECT name,value FROM metadata'))
    if old:
        if json.loads(old['identity']) != expected:
            conn.close()
            raise ValueError('Native checkpoint source/config mismatch')
    else:
        with conn:
            conn.execute('INSERT INTO metadata VALUES (?,?)', ('identity', dump(expected)))
            conn.executemany('INSERT INTO progress VALUES (?, -1, 0)', [(f,) for f in families])
    stats = json.loads(old.get('stats', '{}')) or {
        'generated': 0, 'candidates': 0, 'contexts_evaluated': 0, 'batches': 0,
        'generation_seconds': 0.0, 'scoring_seconds': 0.0, 'elapsed_seconds': 0.0}
    # This cache holds only discovered combinations/categories. Physical keys
    # remain on disk and never need to be replayed into a Python set.
    known = set(conn.execute('SELECT key,policy,closed,method FROM observations'))
    totals = dict(conn.execute("SELECT key,total FROM observations WHERE policy='all_optimal'"))
    start = time.perf_counter()
    start_elapsed = stats['elapsed_seconds']
    termination = 'running'

    def snapshot():
        progress = {f: {'cursor': c, 'complete': bool(done)}
                    for f, c, done in conn.execute('SELECT * FROM progress')}
        scope_complete = all(row['complete'] for row in progress.values())
        all_keys = {k for k, p, c, m in known if p == 'all_optimal'}
        canonical = {k for k, p, c, m in known if p == 'canonical'}
        distribution = Counter(totals.values())
        return dict(stats, schema_version=1, backend='native-cpu-v1', config=config,
                    source_sha256=expected['fingerprint'], partitions=progress,
                    scope_complete=scope_complete,
                    complete=scope_complete and set(families) == set(FAMILIES)
                    and tiles == tuple(range(34)) and include_melds
                    and left_begin == 0 and left_end is None
                    and min_fan == 8 and max_fan is None,
                    combination_count=len(all_keys), canonical_count=len(canonical),
                    observation_count=len(known), fan_distribution=dict(sorted(distribution.items())),
                    termination=termination, limits_checked='between committed batches',
                    evidence='finite physical enumeration; independent exact Python scoring')

    try:
        for family in families:
            while True:
                cursor, done = conn.execute('SELECT cursor,complete FROM progress WHERE family=?',
                                            (family,)).fetchone()
                if done:
                    break
                if max_candidates and stats['candidates'] >= max_candidates:
                    termination = 'candidate_limit'
                    break
                if seconds and time.perf_counter()-start >= seconds:
                    termination = 'time_limit'
                    break
                # Limits apply to unique candidates; a batch may contain
                # duplicates, so cap generated records conservatively.
                size = min(batch_size, max_candidates-stats['candidates']) if max_candidates else batch_size
                began = time.perf_counter()
                generated = generate_batch(executable, output/'batch.bin', family=family,
                                           tiles=tiles, after=cursor, max_records=size,
                                           include_melds=include_melds,
                                           left_begin=left_begin, left_end=left_end)
                generation_seconds = time.perf_counter()-began
                rows = list(read_batch(output/'batch.bin'))
                if len(rows) != generated['records']:
                    raise ValueError('Native record count mismatch')
                began = time.perf_counter()
                # Keep in-memory accounting aligned with a committed database
                # if any exception interrupts evaluation or commit.
                next_stats = dict(stats)
                added = set()
                added_totals = {}
                with conn:
                    for rank, identity in rows:
                        inserted = conn.execute('INSERT OR IGNORE INTO physical VALUES (?)',
                                                (identity,)).rowcount
                        if not inserted:
                            continue
                        data = decode(identity)
                        next_stats['candidates'] += 1
                        for expanded, result in expand(data, equivalent_winds=equivalent_winds):
                            next_stats['contexts_evaluated'] += 1
                            total = result['total']
                            if total < min_fan or (max_fan is not None and total > max_fan):
                                continue
                            for policy, choices in (('all_optimal', result['optimal']),
                                                    ('canonical', (result['canonical'],))):
                                for interpretation in choices:
                                    key = dump(interpretation['key'])
                                    tag = (key, policy, int(result['closed']), result['method'])
                                    if tag in known or tag in added:
                                        continue
                                    evidence = dump({'input': expanded, 'interpretation': interpretation,
                                                     'certificate': result['certificate'], 'partition': family})
                                    conn.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',
                                                 (*tag, total, evidence))
                                    added.add(tag)
                                    if policy == 'all_optimal':
                                        added_totals[key] = total
                    next_stats['generated'] += len(rows)
                    next_stats['batches'] += 1
                    next_stats['generation_seconds'] += generation_seconds
                    next_stats['scoring_seconds'] += time.perf_counter()-began
                    next_stats['elapsed_seconds'] = start_elapsed+time.perf_counter()-start
                    conn.execute('UPDATE progress SET cursor=?,complete=? WHERE family=?',
                                 (generated['cursor'], int(generated['complete']), family))
                    conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('stats', dump(next_stats)))
                stats = next_stats
                known.update(added)
                totals.update(added_totals)
                write_json(output/'summary.json', snapshot())
                print(dump({'family': family, 'candidates': stats['candidates'],
                            'generated': stats['generated'], 'contexts': stats['contexts_evaluated'],
                            'seconds': round(time.perf_counter()-start, 2)}), flush=True)
            if termination != 'running':
                break
        else:
            termination = 'exhausted'
    except KeyboardInterrupt:
        termination = 'interrupted'
    except Exception:
        termination = 'error'
        raise
    finally:
        # A signal can arrive immediately after commit but before the Python
        # caches are updated. Recover accounting from the authoritative DB.
        committed = conn.execute("SELECT value FROM metadata WHERE name='stats'").fetchone()
        if committed:
            stats = json.loads(committed[0])
        known = set(conn.execute('SELECT key,policy,closed,method FROM observations'))
        totals = dict(conn.execute("SELECT key,total FROM observations WHERE policy='all_optimal'"))
        stats['elapsed_seconds'] = start_elapsed+time.perf_counter()-start
        with conn:
            conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('stats', dump(stats)))
        summary = snapshot()
        write_json(output/'summary.json', summary)
        if export_results:
            export(conn, output)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.close()
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--families', nargs='+', choices=FAMILIES, default=list(FAMILIES))
    p.add_argument('--tiles', help='Restricted tile kinds in compact notation; default all 34')
    p.add_argument('--concealed-only', action='store_true')
    p.add_argument('--left-begin', type=int, default=0)
    p.add_argument('--left-end', type=int)
    p.add_argument('--batch-size', type=int, default=1024)
    p.add_argument('--max-candidates', type=int, default=0, help='Cumulative unique-state cap')
    p.add_argument('--seconds', type=float, default=0, help='Per-invocation budget; checked between batches')
    p.add_argument('--min-fan', type=int, default=8)
    p.add_argument('--max-fan', type=int)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--full-winds', action='store_true', help='Disable exact wind equivalence reduction')
    p.add_argument('--no-export', action='store_true')
    a = p.parse_args()
    summary = run(a.output, families=tuple(a.families),
                  tiles=parse(a.tiles) if a.tiles else tuple(range(34)),
                  include_melds=not a.concealed_only, left_begin=a.left_begin, left_end=a.left_end,
                  batch_size=a.batch_size, max_candidates=a.max_candidates, seconds=a.seconds,
                  resume=a.resume, export_results=not a.no_export, min_fan=a.min_fan,
                  max_fan=a.max_fan, equivalent_winds=not a.full_winds)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['scope_complete'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
