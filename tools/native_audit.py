"""Re-score every retained native witness with the independent Python scorer."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calc_fan import evaluate
from enumerate_combinations import write_json
from tools.native_census import dump


def audit(directory):
    path = (Path(directory)/'census.sqlite3').resolve()
    checked = 0
    errors = []
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as conn:
        merged = conn.execute("SELECT value FROM metadata WHERE name='merged_scope'").fetchone()
        scope = json.loads(merged[0]) if merged else {}
        min_fan = scope.get('min_fan', 8)
        max_fan = scope.get('max_fan')
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        for key, policy, closed, method, total, evidence in conn.execute('SELECT * FROM observations'):
            row = json.loads(evidence)
            result = evaluate(row['input'])
            choices = result['optimal'] if policy == 'all_optimal' else [result['canonical']]
            valid = (result['total'] >= min_fan and (max_fan is None or result['total'] <= max_fan) and result['total'] == total
                     and result['closed'] == bool(closed) and result['method'] == method
                     and key in {dump(i['key']) for i in choices})
            if not valid:
                errors.append({'key':key,'policy':policy,'input':row['input']})
            checked += 1
    return {'passed':integrity == 'ok' and not errors,'integrity':integrity,
            'observations_checked':checked,'errors':errors,
            'min_fan':min_fan,
            'max_fan':max_fan,
            'boundary':'positive-witness audit; does not establish exhaustive coverage'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory')
    a = p.parse_args()
    result = audit(a.directory)
    write_json(Path(a.directory)/'witness-audit.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
