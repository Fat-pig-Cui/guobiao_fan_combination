"""Encode hand-written candidates and run the CPU/CUDA feature filter."""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from decompose import parse
from hand_solver import iter_inputs

HEADER = struct.Struct('<4sII')
CANDIDATE = struct.Struct('<34BBB')
RESULT = struct.Struct('<QHBB')

FEATURE_NAMES = {
    0: 'all_honors', 1: 'all_terminals', 2: 'all_green', 3: 'no_honors',
    4: 'one_number_suit', 5: 'three_number_suits', 6: 'has_winds',
    7: 'has_dragons', 8: 'has_terminals',
}


def candidate_record(data, family):
    counts = Counter(parse(data['hand']) + parse(data['win']))
    for meld in data.get('melds', []):
        counts.update(parse(meld['tiles']))
    return CANDIDATE.pack(*(counts[t] for t in range(34)),
                          parse(data['win'])[0], family)


def python_classify(record, required):
    values = CANDIDATE.unpack(record)
    counts, win, family = values[:34], values[34], values[35]
    all_honors = all(not counts[t] or t >= 27 for t in range(34))
    all_terminals = all(not counts[t] or (t < 27 and t % 9 in (0, 8)) for t in range(34))
    all_green = all(not counts[t] or t in (19, 20, 21, 23, 25, 32) for t in range(34))
    no_honors = not any(counts[t] for t in range(27, 34))
    suit_mask = 0
    has_winds = has_dragons = has_terminals = False
    total = 0
    for tile, count in enumerate(counts):
        if not count:
            continue
        total += count
        if tile < 27:
            suit_mask |= 1 << (tile // 9)
            has_terminals |= tile % 9 in (0, 8)
        elif tile < 31:
            has_winds = True
        else:
            has_dragons = True
    features = 0
    features |= (1 << 0) if all_honors else 0
    features |= (1 << 1) if all_terminals else 0
    features |= (1 << 2) if all_green else 0
    features |= (1 << 3) if no_honors else 0
    features |= (1 << 4) if suit_mask and suit_mask & (suit_mask - 1) == 0 and no_honors else 0
    features |= (1 << 5) if suit_mask & 0x7 == 0x7 else 0
    features |= (1 << 6) if has_winds else 0
    features |= (1 << 7) if has_dragons else 0
    features |= (1 << 8) if has_terminals else 0
    return RESULT.pack(features, total, suit_mask, int(features & required == required))


def write_candidates(records, path):
    with Path(path).open('wb') as stream:
        stream.write(HEADER.pack(b'MCR1', 1, len(records)))
        for record in records:
            stream.write(record)


def read_results(path):
    with Path(path).open('rb') as stream:
        header = stream.read(HEADER.size)
        magic, version, count = HEADER.unpack(header)
        if magic != b'MCRF' or version != 1:
            raise ValueError('Invalid MCRF result header')
        payload = stream.read()
    if len(payload) != count * RESULT.size:
        raise ValueError('MCRF result length mismatch')
    return [RESULT.unpack(payload[i:i + RESULT.size]) for i in range(0, len(payload), RESULT.size)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--jsonl', type=Path, help='Physical inputs, one JSON object per line')
    source.add_argument('--family', choices=('standard', 'seven_pairs', 'orphans', 'unconnected', 'knitted'))
    parser.add_argument('--input-bin', type=Path, required=True)
    parser.add_argument('--result-bin', type=Path, required=True)
    parser.add_argument('--count', type=int, default=1000)
    parser.add_argument('--prefix', type=int)
    parser.add_argument('--concealed-only', action='store_true')
    parser.add_argument('--required-mask', type=int, default=0)
    parser.add_argument('--executable', type=Path,
                        help='mahjong_feature_filter; omitted uses the Python fallback')
    parser.add_argument('--verify-cpu', action='store_true',
                        help='Compare external results with the Python reference')
    args = parser.parse_args()
    if args.count < 0 or args.required_mask < 0:
        parser.error('count and required-mask must be nonnegative')
    if args.family and args.prefix is not None and not 0 <= args.prefix < 34:
        parser.error('prefix must be 0..33')
    records = []
    if args.jsonl:
        with args.jsonl.open(encoding='utf-8') as stream:
            for line in stream:
                if line.strip():
                    records.append(candidate_record(json.loads(line), 0))
                    if len(records) >= args.count:
                        break
    else:
        for data in iter_inputs(args.family, include_melds=not args.concealed_only,
                                prefix=args.prefix) if args.family == 'standard' \
                else iter_inputs(args.family):
            records.append(candidate_record(data, 0))
            if len(records) >= args.count:
                break
    write_candidates(records, args.input_bin)
    if args.executable:
        subprocess.run([str(args.executable), str(args.input_bin), str(args.result_bin),
                        str(args.required_mask)], check=True)
    else:
        with args.result_bin.open('wb') as stream:
            stream.write(HEADER.pack(b'MCRF', 1, len(records)))
            for record in records:
                stream.write(python_classify(record, args.required_mask))
    results = read_results(args.result_bin)
    if args.verify_cpu and args.executable:
        expected = [python_classify(record, args.required_mask) for record in records]
        if results != [RESULT.unpack(value) if isinstance(value, bytes) else value for value in expected]:
            raise SystemExit('external feature results differ from Python reference')
    passed = sum(row[3] for row in results)
    print(json.dumps({'candidates': len(records), 'passed': passed,
                      'backend': 'external' if args.executable else 'python',
                      'required_mask': args.required_mask}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
