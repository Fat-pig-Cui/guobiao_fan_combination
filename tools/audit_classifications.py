"""Rescore positive labels, validate analytic negatives and inventory solver proofs."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calc_fan import evaluate
from enumerate_combinations import fingerprint, read_records, key_tuple, write_json
from tools.classify_combinations import LABELS, label_matches, ruled_out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory')
    p.add_argument('--source', required=True)
    a = p.parse_args()
    directory, source = Path(a.directory), Path(a.source)
    summary = json.loads((directory/'summary.json').read_text())
    source_summary = json.loads((source/'summary.json').read_text())
    if (summary['source_sha256'] != fingerprint() or source_summary['source_sha256'] != fingerprint()
            or summary['policy'] != source_summary['policy']):
        p.error('Source fingerprint/policy mismatch')
    if source_summary.get('expansion_sha256'):
        from context_expansion import source_hash
        if source_summary['expansion_sha256']!=source_hash():p.error('Context expansion fingerprint mismatch')
    keys = {key_tuple(row['key']) for row in read_records(source/'combinations.jsonl')}
    done = {}
    for row in read_records(directory/'classifications.jsonl'):
        key, label, result = key_tuple(row['key']), row['label'], row['result']
        if key not in keys or result['status'] == 'unknown':
            continue
        previous = done.get((key, label))
        if previous and previous['status'] != result['status']:
            raise ValueError('Contradictory classification records')
        done[key, label] = result
    positives = analytic = stored_solver_proofs = 0
    for (key, label), result in done.items():
        if label not in LABELS:
            raise ValueError('Unknown label')
        if result['status'] == 'yes':
            r = evaluate(result['input'])
            choices = r['optimal'] if summary['policy'] == 'all_optimal' else [r['canonical']]
            if (not r['eligible'] or key not in {key_tuple(i['key']) for i in choices}
                    or not label_matches(r, label) or result['certificate'] != r['certificate']):
                raise ValueError('Invalid positive label witness')
            positives += 1
        elif result['status'] == 'no':
            if ruled_out(key, label):
                analytic += 1
            elif result.get('proof') == 'all five structural partitions unsat under fixed vector and label':
                stored_solver_proofs += 1
            else:
                raise ValueError('Unrecognized negative evidence')
        else:
            raise ValueError('Unknown classification status')
    sets = {label: {key for key in keys if done.get((key, label), {}).get('status') == 'yes'}
            for label in LABELS}
    complete = len(done) == 4*len(keys)
    result = {'passed': True, 'policy':summary['policy'], 'keys': len(keys), 'resolved': len(done),
              'classification_complete': complete, 'global_complete': complete and source_summary['complete'],
              'positive_witnesses_recomputed': positives, 'analytic_negatives_checked': analytic,
              'stored_solver_negatives': stored_solver_proofs,
              'yes_counts': {label: len(values) for label, values in sets.items()},
              'closed_and_opened': len(sets['closed'] & sets['opened']),
              'ron_and_tsumo': len(sets['ron'] & sets['tsumo']),
              'source_sha256': fingerprint(),
              'negative_evidence_note': 'Stored unsat queries are inventoried, not independently rerun.'}
    write_json(directory/'audit.json', result)
    lines = ['# 组合可行性分类', '', f"计法：`{summary['policy']}`；组合集合：{len(keys)}种。", '',
             f"四项判断已解决{len(done)}/{4*len(keys)}项。分类完成：{'是' if complete else '否'}；"
             f"全量搜索与分类均完成：{'是' if result['global_complete'] else '否'}。", '',
             '| 分类 | 可行组合数 |', '|---|---:|']
    lines += [f'| {label} | {len(sets[label])} |' for label in LABELS]
    lines += ['', f"门清与副露交集：{result['closed_and_opened']}；点和与自摸交集：{result['ron_and_tsumo']}。", '',
              '同一组合可属于两个和牌方式，分类数不能直接相加当作主总数。', '',
              f'已逐条重算{positives}个正例见证，检查{analytic}项规则蕴含负例。'
              f'另有{stored_solver_proofs}项五结构分区均unsat的已存查询证明，本次未逐条重跑求解。', '']
    (directory/'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
