"""Portable process locks and lossless standard-prefix checkpoint splitting."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from enumerate_combinations import FAMILIES, write_json
from native_backend import build, generate_batch
from tools.native_census import fingerprint, dump


@contextmanager
def controller_lock(path):
    with Path(path).open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.seek(0,2) == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(stream,fcntl.LOCK_UN)


def task_specs(output):
    path = Path(output)/'tasks.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))['tasks']
    return [{'id':f,'family':f,'directory':f,'left_begin':0,'left_end':None} for f in FAMILIES]


def split_standard(output, *, rows_per_task=16):
    """Narrow the copied prefix checkpoint, leaving its original untouched.

    The original full-domain traversal starts at row zero. All committed
    records have rank <= cursor, so choosing the first shard's end above the
    cursor's row preserves every processed record and excludes no work done.
    """
    output = Path(output)
    if rows_per_task < 1:
        raise ValueError('rows_per_task must be positive')
    with controller_lock(output/'controller.lock'):
        if (output/'tasks.json').exists():
            return json.loads((output/'tasks.json').read_text())
        source = (output/'standard'/'census.sqlite3').resolve()
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src:
            metadata = dict(src.execute('SELECT name,value FROM metadata'))
            identity = json.loads(metadata['identity'])
            config = identity['config']
            cursor,complete = src.execute("SELECT cursor,complete FROM progress WHERE family='standard'").fetchone()
            if (identity['fingerprint'] != fingerprint() or config['families'] != ['standard']
                    or config['left_begin'] != 0 or config['left_end'] is not None):
                raise ValueError('Expected an unchanged, unsharded standard checkpoint')
            if complete:
                raise ValueError('Completed standard family does not need splitting')
            with tempfile.TemporaryDirectory(prefix='mcr-shard-layout-') as tmp:
                info = generate_batch(build(),Path(tmp)/'probe.bin',tiles=config['tiles'],
                                      include_melds=config['include_melds'],max_records=1)
            count = info['pairs']
            if not count:
                raise ValueError('No standard pair rows')
            row = max(0,cursor)//(count*34*256*34)
            first_end = min(count,((row//rows_per_task)+1)*rows_per_task)
            if row >= first_end:
                raise ValueError('Checkpoint cursor lies outside requested first shard')
            intervals = [(0,first_end)]
            intervals.extend((a,min(a+rows_per_task,count)) for a in range(first_end,count,rows_per_task))
            specs = [{'id':f'standard-{a:04d}-{b:04d}','family':'standard',
                      'directory':f'standard-shards/left-{a:04d}-{b:04d}',
                      'left_begin':a,'left_end':b} for a,b in intervals]
            first = output/specs[0]['directory']
            first.mkdir(parents=True,exist_ok=False)
            changed = copy.deepcopy(identity)
            changed['config']['left_end'] = first_end
            with sqlite3.connect(first/'census.sqlite3') as dst:
                src.backup(dst)
                dst.execute('UPDATE metadata SET value=? WHERE name=?',(dump(changed),'identity'))
                dst.commit()
                if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Copied standard checkpoint failed integrity check')
            summary = json.loads((output/'standard'/'summary.json').read_text())
            summary['config'] = changed['config']
            write_json(first/'summary.json',summary)
        specials = [{'id':f,'family':f,'directory':f,'left_begin':0,'left_end':None}
                    for f in ('knitted','seven_pairs','orphans','unconnected')]
        tasks = specs[:1]+specials[:2]+specs[1:]+specials[2:]
        plan = {'schema_version':1,'pair_rows':count,'rows_per_task':rows_per_task,
                'original_standard_directory':'standard','original_cursor':cursor,
                'cursor_row':row,'first_shard_end':first_end,'tasks':tasks,
                'migration':'SQLite backup; narrow first interval above committed cursor; original retained',
                'source_sha256':identity['fingerprint']}
        write_json(output/'tasks.json',plan)
        return plan
