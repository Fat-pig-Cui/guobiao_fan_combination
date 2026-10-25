"""Reproducible full-small-domain generation and scoring comparisons.

Each timed worker is a fresh interpreter. Both scoring paths install the same
runtime caches; native generation and exact wind reduction are the variables.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from context_expansion import expand
from decompose import compact, parse
from enumerate_combinations import write_json
from fast_runtime import install
from native_backend import build, decode, generate_batch, physical_key, read_batch
from tools.direct_shapes import standard_states
from tools.native_census import dump, fingerprint


def digest(values):
    return hashlib.sha256(b'\n'.join(sorted(values))).hexdigest()


def worker(mode, notation):
    tiles = set(parse(notation))
    install()
    executable = build()  # compilation is not part of enumeration timing
    began = time.perf_counter()
    if mode == 'reference':
        physical = set()
        raw = 0
        for hand, win, fixed in standard_states(tiles):
            raw += 1
            physical.add(physical_key({'hand': compact(hand), 'win': compact((win,)),
                                      'melds': [{'kind':g.kind, 'tiles':compact(g.tiles)} for g in fixed]}))
    else:
        with tempfile.TemporaryDirectory(prefix='mcr-native-benchmark-') as tmp:
            path = Path(tmp)/'batch.bin'
            info = generate_batch(executable,path,tiles=tiles,max_records=0)
            if not info['complete']:
                raise RuntimeError('Benchmark generation incomplete')
            raw = info['records']
            physical = {p for rank,p in read_batch(path)}
    generation = time.perf_counter()-began
    keys = set()
    contexts = 0
    began = time.perf_counter()
    for identity in sorted(physical):
        for candidate, result in expand(decode(identity),equivalent_winds=mode == 'native'):
            contexts += 1
            if not result['eligible']:
                continue
            for policy, choices in (('all_optimal',result['optimal']),('canonical',[result['canonical']])):
                for interpretation in choices:
                    keys.add(dump([interpretation['key'],policy,result['closed'],result['method']]).encode())
    scoring = time.perf_counter()-began
    return {'mode':mode,'tiles':notation,'physical_states':len(physical),'raw_records':raw,
            'physical_sha256':digest(physical),'observations':len(keys),'observation_sha256':digest(keys),
            'contexts':contexts,'generation_seconds':generation,'scoring_seconds':scoring,
            'generation_and_scoring_seconds':generation+scoring,
            'boundary':'complete restricted standard family; identical caches; no SQLite or JSON export timing'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path)
    p.add_argument('--tiles', nargs='+', default=['1234m','12345z'])
    p.add_argument('--worker', choices=['reference','native'])
    a = p.parse_args()
    if a.worker:
        print(json.dumps(worker(a.worker,a.tiles[0])))
        return
    if a.output is None:
        p.error('--output is required')
    build()
    rows = []
    for notation in a.tiles:
        row = {}
        for mode in ('reference','native'):
            result = subprocess.run([sys.executable,__file__,'--worker',mode,'--tiles',notation],
                                    check=True,text=True,capture_output=True)
            row[mode] = json.loads(result.stdout)
        old,new = row['reference'],row['native']
        row['equal'] = (old['physical_sha256'] == new['physical_sha256']
                        and old['observation_sha256'] == new['observation_sha256'])
        row['generation_speedup'] = old['generation_seconds']/new['generation_seconds']
        row['generation_and_scoring_speedup'] = (old['generation_and_scoring_seconds']
                                               /new['generation_and_scoring_seconds'])
        rows.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    report = {'passed':all(r['equal'] for r in rows),'platform':platform.platform(),
              'python':sys.version,'source_sha256':fingerprint(),'partitions':rows,
              'boundary':'bounded complete comparisons, not whole-domain enumeration or Windows measurements'}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    write_json(a.output,report)
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
