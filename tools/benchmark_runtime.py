"""Compare baseline and memoized context expansion on saved inventories."""
import argparse
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_inputs(results, count):
    rows = []
    seen = set()
    for path in sorted((results / 'bands').glob('*/inventories.jsonl')):
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                data = row['input']
                token = json.dumps({k: data[k] for k in ('hand', 'win', 'melds')},
                                   sort_keys=True, ensure_ascii=False)
                if token in seen:
                    continue
                seen.add(token)
                rows.append(data)
                if len(rows) >= count:
                    return rows
    if not rows:
        raise ValueError('No inventory records found')
    return rows


def run(inputs, optimized):
    if optimized:
        from fast_runtime import install
        install()
    from context_expansion import expand

    start = time.perf_counter()
    contexts = 0
    eligible = 0
    digest = hashlib.sha256()
    for data in inputs:
        for expanded, result in expand(data):
            contexts += 1
            if result['eligible']:
                eligible += 1
            keys = [tuple(tuple(pair) for pair in item['key'])
                    for item in result['optimal']]
            digest.update(json.dumps(keys, sort_keys=True).encode('ascii'))
    elapsed = time.perf_counter() - start
    output = {'optimized': optimized, 'inputs': len(inputs), 'contexts': contexts,
              'eligible_contexts': eligible, 'seconds': round(elapsed, 6),
              'contexts_per_second': round(contexts / elapsed, 3),
              'digest': digest.hexdigest()}
    if optimized:
        from fast_runtime import stats
        output['cache'] = stats()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', default='results')
    parser.add_argument('--count', type=int, default=1000)
    parser.add_argument('--mode', choices=('baseline', 'optimized'), required=True)
    args = parser.parse_args()
    inputs = load_inputs(pathlib.Path(args.results), args.count)
    print(json.dumps(run(inputs, args.mode == 'optimized'), ensure_ascii=False,
                     indent=2))


if __name__ == '__main__':
    main()
