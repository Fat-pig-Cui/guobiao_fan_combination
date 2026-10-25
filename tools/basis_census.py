"""Checkpointed geometry-native scoring; store observations, not physical inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from basis_backend import batch, build, fingerprint as backend_fingerprint, key_bytes, write_known
from decompose import parse
from enumerate_combinations import FAMILIES, write_json
from rules import PROFILE
from tools.native_census import dump, export


def fingerprint():
    return dict(backend_fingerprint(), **{
        'tools/basis_census.py':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})


def connect(path):
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=FULL')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS progress (family TEXT PRIMARY KEY, cursor INTEGER NOT NULL,
                                             complete INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS observations (
            key TEXT NOT NULL, policy TEXT NOT NULL, closed INTEGER NOT NULL,
            method TEXT NOT NULL, total INTEGER NOT NULL, evidence TEXT NOT NULL,
            PRIMARY KEY (key,policy,closed,method)) WITHOUT ROWID;
    ''')
    return conn


def configuration(family, tiles, include_melds, left_begin, left_end, min_fan=8, max_fan=None):
    return {'family':family, 'tiles':list(tiles), 'include_melds':include_melds,
            'left_begin':left_begin, 'left_end':left_end, 'profile':PROFILE,
            'min_fan':min_fan, 'max_fan':max_fan, 'policies':['all_optimal','canonical']}


def run(output, *, family='standard', tiles=tuple(range(34)), include_melds=True,
        left_begin=0, left_end=None, batch_bases=4096, batch_seconds=5,
        seconds=0, max_bases=0, resume=False, pause_file=None, export_results=True,
        min_fan=8, max_fan=None, on_batch=None):
    output = Path(output)
    tiles = tuple(sorted(set(tiles)))
    if (family not in FAMILIES or min_fan < 0 or (max_fan is not None and max_fan < min_fan) or
            not tiles or any(type(t) is not int or not 0<=t<34 for t in tiles)
            or batch_bases<1 or batch_seconds<=0 or seconds<0 or max_bases<0
            or left_begin<0 or (left_end is not None and left_end<=left_begin)
            or (family!='standard' and (left_begin or left_end is not None))):
        raise ValueError('Invalid basis configuration or limits')
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError('Output exists; use --resume or a new directory')
    if resume and not (output/'census.sqlite3').exists():
        raise ValueError('No basis checkpoint to resume')
    build()
    output.mkdir(parents=True, exist_ok=True)
    conn = connect(output/'census.sqlite3')
    identity = {'backend':'basis-cpu-v1','fingerprint':fingerprint(),
                'config':configuration(family,tiles,include_melds,left_begin,left_end,min_fan,max_fan)}
    old = dict(conn.execute('SELECT name,value FROM metadata'))
    if old and json.loads(old['identity']) != identity:
        conn.close()
        raise ValueError('Basis checkpoint source/config mismatch; old native checkpoints are not interchangeable')
    if not old:
        with conn:
            conn.execute('INSERT INTO metadata VALUES (?,?)',('identity',dump(identity)))
            conn.execute('INSERT INTO progress VALUES (?, -1, 0)',(family,))
    stats = json.loads(old.get('stats','{}')) or {
        'bases':0,'physical':0,'contexts':0,'decompositions':0,'wait_checks':0,
        'batches':0,'native_seconds':0.,'elapsed_seconds':0.}
    start = time.perf_counter()
    start_elapsed = stats['elapsed_seconds']
    known_file = output/'known.bin'
    write_known(known_file, conn.execute('SELECT key,policy,closed,method FROM observations'))
    termination = 'running'

    def snapshot():
        cursor,complete = conn.execute('SELECT cursor,complete FROM progress WHERE family=?',(family,)).fetchone()
        rows = conn.execute('SELECT policy,count(*),count(DISTINCT key) FROM observations GROUP BY policy').fetchall()
        counts = {p:{'observations':n,'combinations':k} for p,n,k in rows}
        return dict(stats,backend='basis-cpu-v1',identity=identity,cursor=cursor,
                    scope_complete=bool(complete),complete=False,termination=termination,
                    observation_count=sum(v['observations'] for v in counts.values()),
                    combination_count=counts.get('all_optimal',{}).get('combinations',0),
                    canonical_count=counts.get('canonical',{}).get('combinations',0),
                    checkpoint_unit='one complete geometry including declarations, winning tiles and contexts',
                    evidence='finite basis enumeration; native exact scorer; positive Python audit required')
    try:
        while True:
            cursor,done = conn.execute('SELECT cursor,complete FROM progress WHERE family=?',(family,)).fetchone()
            if done:
                termination='exhausted';break
            if pause_file and Path(pause_file).exists():
                termination='interrupted';break
            if seconds and time.perf_counter()-start>=seconds:
                termination='time_limit';break
            if max_bases and stats['bases']>=max_bases:
                termination='basis_limit';break
            if fingerprint()!=identity['fingerprint']:
                raise ValueError('Sources changed during basis run')
            size=min(batch_bases,max_bases-stats['bases']) if max_bases else batch_bases
            native,observations=batch(output,family=family,tiles=tiles,include_melds=include_melds,
                                      after=cursor,max_bases=size,seconds=batch_seconds,
                                      left_begin=left_begin,left_end=left_end,
                                      # Low-fan runs intentionally let SQLite
                                      # perform the cross-batch primary-key
                                      # de-duplication.  Re-reading a rapidly
                                      # growing known.bin for every short native
                                      # slice is much slower than discarding
                                      # duplicate rows at commit time.
                                      known=known_file if min_fan >= 8 else None,
                                      all_results=min_fan < 8, max_fan=max_fan)
            if fingerprint()!=identity['fingerprint']:
                raise ValueError('Sources changed before batch commit')
            if not native['complete'] and native['cursor']<=cursor:
                raise ValueError('Native cursor did not advance')
            next_stats=dict(stats)
            for k in ('bases','physical','contexts','decompositions','wait_checks'):
                next_stats[k]+=native[k]
            next_stats['batches']+=1
            next_stats['native_seconds']+=native['seconds']
            next_stats['elapsed_seconds']=start_elapsed+time.perf_counter()-start
            # This transaction is the only authority. Native keys and progress
            # become visible together; a killed subprocess leaves no advance.
            with conn:
                for row in observations:
                    conn.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',
                                 (dump(row['key']),row['policy'],int(row['closed']),row['method'],
                                  row['total'],dump({'input':row['input'],'partition':family,
                                                     'backend':'basis-cpu-v1'})))
                conn.execute('UPDATE progress SET cursor=?,complete=? WHERE family=?',
                             (native['cursor'],int(native['complete']),family))
                conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('stats',dump(next_stats)))
            stats=next_stats
            if min_fan >= 8:
                with known_file.open('ab') as stream:
                    for row in observations:
                        stream.write(key_bytes(row['key'],row['policy'],row['closed'],row['method']))
            write_json(output/'summary.json',snapshot())
            print(dump({'family':family,'bases':stats['bases'],'physical':stats['physical'],
                        'contexts':stats['contexts'],'seconds':round(time.perf_counter()-start,2)}),flush=True)
            if on_batch:
                on_batch(conn)
    except KeyboardInterrupt:
        termination='interrupted'
    except BaseException:
        termination='error';raise
    finally:
        committed=conn.execute("SELECT value FROM metadata WHERE name='stats'").fetchone()
        if committed:
            stats=json.loads(committed[0])
        stats['elapsed_seconds']=start_elapsed+time.perf_counter()-start
        with conn:
            conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('stats',dump(stats)))
        summary=snapshot()
        write_json(output/'summary.json',summary)
        if export_results:
            export(conn,output)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.close()
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--family',choices=FAMILIES,default='standard')
    p.add_argument('--tiles')
    p.add_argument('--concealed-only',action='store_true')
    p.add_argument('--left-begin',type=int,default=0)
    p.add_argument('--left-end',type=int)
    p.add_argument('--batch-bases',type=int,default=4096)
    p.add_argument('--batch-seconds',type=float,default=5)
    p.add_argument('--seconds',type=float,default=0)
    p.add_argument('--max-bases',type=int,default=0)
    p.add_argument('--min-fan',type=int,default=8)
    p.add_argument('--max-fan',type=int)
    p.add_argument('--pause-file',type=Path)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--no-export',action='store_true')
    a=p.parse_args()
    # Also protects against orphaned workers after a controller crash.
    from tools.native_parallel import controller_lock
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with controller_lock(a.output.parent/(a.output.name+'.worker.lock')):
        result=run(a.output,family=a.family,tiles=parse(a.tiles) if a.tiles else tuple(range(34)),
                   include_melds=not a.concealed_only,left_begin=a.left_begin,left_end=a.left_end,
                   batch_bases=a.batch_bases,batch_seconds=a.batch_seconds,seconds=a.seconds,
                   max_bases=a.max_bases,pause_file=a.pause_file,resume=a.resume,
                   export_results=not a.no_export,min_fan=a.min_fan,max_fan=a.max_fan)
    print(dump(result))
    raise SystemExit(0 if result['scope_complete'] else 3)


if __name__=='__main__':
    main()
