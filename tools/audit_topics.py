"""Rescore every topic witness and publish a compact Markdown inventory."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calc_fan import evaluate
from enumerate_combinations import fingerprint, key_tuple, read_records, write_json
from rules import describe


def matches(interpretation, topic):
    if interpretation['total'] != 8:
        return False
    from rules import FANS
    key = key_tuple(interpretation['key'])
    if topic == 'gold':
        return all(FANS[fan]['value'] == 1 for fan, _ in key)
    return (sum(n for fan, n in key if FANS[fan]['value'] == 2) == 1
            and sum(n for fan, n in key if FANS[fan]['value'] == 1) == 6)


def audit(directory):
    directory = Path(directory)
    summary = json.loads((directory / 'summary.json').read_text())
    if summary['source_sha256'] != fingerprint():
        raise ValueError('Source fingerprint mismatch')
    seen = set()
    rows = []
    for row in read_records(directory / 'combinations.jsonl'):
        key = key_tuple(row['key'])
        result = evaluate(row['input'])
        choices = result['optimal'] if summary['policy'] == 'all_optimal' else [result['canonical']]
        if key in seen or not result['eligible'] or not any(
                key == key_tuple(i['key']) and matches(i, summary['topic']) for i in choices):
            raise ValueError('Invalid or duplicate topic witness: ' + repr(key))
        if result['certificate'] != row['certificate']:
            raise ValueError('Certificate mismatch')
        seen.add(key)
        rows.append((key, row['input']))
    if len(seen) != summary['count']:
        raise ValueError('Summary count mismatch')
    audit_result = {'passed': True, 'witnesses': len(seen), 'complete': summary['complete'],
                    'topic': summary['topic'], 'policy': summary['policy']}
    write_json(directory / 'audit.json', audit_result)
    name = '金八番' if summary['topic'] == 'gold' else '银八番'
    lines = ['# ' + name + '专题统计', '',
             f"计法：`{summary['policy']}`；组合数：**{len(seen)}**。", '',
             ('已搜索至 `unsat`，完成当前无花配置和该计法下的专题枚举。'
              if summary['complete'] else '搜索尚未完成，组合数仅为已验证下界。'), '',
             '所有组合的具体输入与计分解释保存在同目录 `combinations.jsonl`，已逐条独立复算。', '',
             '金八番只含八个1番计分项；银八番恰含一个2番计分项与六个1番计分项。'
             '其他结构族的基础番均已超过8番，因此此专题只需搜索基本形。', '',
             '| 编号 | 番种组合 |', '|---|---|']
    for index, (key, _) in enumerate(sorted(rows), 1):
        items = describe(key)
        text = '、'.join(item['name'] + (f"×{item['count']}" if item['count'] != 1 else '') for item in items)
        lines.append(f'| {index} | {text} |')
    (directory / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return audit_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
