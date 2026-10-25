"""Compare separately audited statistical policies and publish their set difference."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enumerate_combinations import read_records, key_tuple, write_json, fingerprint
from context_expansion import source_hash


def load(directory, policy):
    directory = Path(directory)
    summary = json.loads((directory/'summary.json').read_text())
    audit = json.loads((directory/'audit.json').read_text())
    if (summary['policy'] != policy or summary['source_sha256'] != fingerprint()
            or (summary.get('expansion_sha256') and summary['expansion_sha256']!=source_hash())
            or not audit['passed'] or audit['witnesses'] != summary['combination_count']):
        raise ValueError('Need matching, audited snapshots: '+str(directory))
    rows = {key_tuple(r['key']): r for r in read_records(directory/'combinations.jsonl')}
    if len(rows) != summary['combination_count']:
        raise ValueError('Snapshot changed after auditing')
    return directory, summary, audit, rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--all-optimal', required=True)
    p.add_argument('--canonical', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--classifications-all')
    p.add_argument('--classifications-canonical')
    a = p.parse_args()
    ad, ass, aa, ar = load(a.all_optimal, 'all_optimal')
    cd, cs, ca, cr = load(a.canonical, 'canonical')
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    both = ar.keys() & cr.keys()
    only_a = ar.keys() - cr.keys()
    only_c = cr.keys() - ar.keys()
    complete = ass['complete'] and cs['complete']
    if complete and only_c:
        raise ValueError('A complete all_optimal set must include the canonical set')
    for name, keys, rows in (('only_all_optimal', only_a, ar), ('only_canonical', only_c, cr)):
        with (out/(name+'.jsonl')).open('w', encoding='utf-8') as stream:
            for key in sorted(keys):
                stream.write(json.dumps(rows[key], ensure_ascii=False)+'\n')
    result = {'complete': complete, 'all_optimal': len(ar), 'canonical': len(cr),
              'intersection': len(both), 'only_all_optimal': len(only_a), 'only_canonical': len(only_c),
              'source_sha256': fingerprint(), 'all_directory': str(ad.resolve()),
              'canonical_directory': str(cd.resolve())}
    classifications=[]
    for path,policy in ((a.classifications_all,'all_optimal'),(a.classifications_canonical,'canonical')):
        if path:
            value=json.loads((Path(path)/'audit.json').read_text())
            expected=len(ar) if policy=='all_optimal' else len(cr)
            if (not value['passed'] or value['source_sha256']!=fingerprint()
                    or value.get('policy')!=policy or value['keys']!=expected):
                raise ValueError('Classification audit mismatch')
            classifications.append((policy,value))
    result['classifications']={policy:value for policy,value in classifications}
    result['max_fan_observed']=max(aa['max_fan_observed'],ca['max_fan_observed'])
    write_json(out/'summary.json', result)
    lines = ['# 国标麻将番种组合综述', '',
             '配置：`editor_no_flower_v1`，136张无花，84个番种名称维度。', '',
             ('全部结构及总番区间已搜索至`unsat`，所有最终见证逐条复算通过。' if complete else
              '全量搜索尚未完成；表中总数及集合差异均为当前快照，不能视为最终结论。'), '',
             '| 统计口径 | 组合数 | 搜索完成 |', '|---|---:|---|',
             f"| 全部同分最优解释 | {len(ar)} | {'是' if ass['complete'] else '否'} |",
             f"| 固定规范计法 | {len(cr)} | {'是' if cs['complete'] else '否'} |", '',
             f'交集{len(both)}种；仅见于全部最优集合{len(only_a)}种；仅见于规范集合{len(only_c)}种。', '',
             '两种结果按番种次数向量去重。同一组合有多种牌形或和牌方式时仍只计一次；'
             '结果不表示实体手牌数量或出现概率。', '',
             '## 八番专题', '',
             '| 专题 | 全部最优计法 | 规范计法 | 搜索完成 |', '|---|---:|---:|---|']
    root = Path(__file__).resolve().parents[1]
    for topic, name in (('gold', '金八番'), ('silver', '银八番')):
        t_all = json.loads((root/'results'/('final-'+topic+'-all-optimal')/'summary.json').read_text())
        t_can = json.loads((root/'results'/('final-'+topic)/'summary.json').read_text())
        if any(t['source_sha256'] != fingerprint() for t in (t_all, t_can)):
            raise ValueError('Topic source fingerprint mismatch')
        completed = t_all['complete'] and t_can['complete']
        lines.append(f"| {name} | {t_all['count']} | {t_can['count']} | {'是' if completed else '否'} |")
    lines += ['', '金八番为八个1番计分项；银八番为一个2番计分项与六个1番计分项，重复计分按次数累计。', '',
              '## 校验与边界', '',
              '最终组合见证、计分解释、事件资源证书与源码指纹均保存在结果目录。'
              '逐番分布和番种出现频率见各目录的`REPORT.md`。', '',
              '同一完整输入可以有多个同分最佳解释；全部最优集合保留它们，规范集合只保留固定优先级的结果。'
              '集合差异的完整输入见同目录`only_all_optimal.jsonl`和`only_canonical.jsonl`。', '',
              '门清／副露、点和／自摸需另做逐组合定向存在性搜索，主见证不代表完整分类。'
              '当前完成性只针对冻结规则与有限结构、事件资源模型，不声称构造了完整四家行牌历史。', '']
    if classifications:
        lines+=['## 可行性分类','','| 计法 | 门清 | 副露 | 点和 | 自摸 | 点和与自摸交集 | 分类完成 |',
                '|---|---:|---:|---:|---:|---:|---|']
        for policy,value in classifications:
            counts=value['yes_counts']
            lines.append(f"| {policy} | {counts['closed']} | {counts['opened']} | {counts['ron']} | {counts['tsumo']} | {value['ron_and_tsumo']} | {'是' if value['global_complete'] else '否'} |")
        lines+=['','门清与副露在本配置下不重叠；点和与自摸可重叠。分类正例均有可复算见证。','']
    (out/'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
