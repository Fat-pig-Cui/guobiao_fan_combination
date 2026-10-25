"""Rescore every published witness without importing the constraint solver."""
import argparse
from collections import Counter
import json
from pathlib import Path
from calc_fan import evaluate
from enumerate_combinations import read_records, key_tuple, fingerprint, write_json
from rules import fan_total, FANS

def audit(directory, *, require_fingerprint=True):
    directory=Path(directory)
    summary=json.loads((directory/'summary.json').read_text())
    if require_fingerprint and summary['source_sha256']!=fingerprint():
        raise ValueError('Source fingerprint mismatch')
    if require_fingerprint and summary.get('expansion_sha256'):
        from context_expansion import source_hash
        if summary['expansion_sha256']!=source_hash():raise ValueError('Context expansion fingerprint mismatch')
    seen=set(); variants=Counter(); counts=Counter(); families=Counter(); fan_counts=Counter()
    max_count=Counter(); closed=set(); opened=set(); ron=set(); tsumo=set()
    gold=set(); silver=set(); max_fan=0
    for row in read_records(directory/'combinations.jsonl'):
        result=evaluate(row['input']); key=key_tuple(row['key'])
        options={key_tuple(r['key']) for r in result['optimal']}
        if summary['policy']=='canonical': options={key_tuple(result['canonical']['key'])}
        if not result['eligible'] or key not in options or row['total']!=result['total']:
            raise ValueError('Witness does not support published combination: '+str(key))
        if row['certificate']!=result['certificate']: raise ValueError('Certificate mismatch')
        if row['closed']!=result['closed'] or row['method']!=result['method']:
            raise ValueError('Classification mismatch')
        if key in seen: raise ValueError('Duplicate primary combination')
        seen.add(key); counts[row['total']]+=1; families[row['interpretation']['family']]+=1
        (closed if row['closed'] else opened).add(key)
        (tsumo if row['method']=='tsumo' else ron).add(key)
        for f,n in key:
            fan_counts[f]+=1; max_count[f]=max(max_count[f],n)
        max_fan=max(max_fan,row['total'])
        if row['total']==8:
            if all(FANS[f]['value']==1 for f,n in key): gold.add(key)
            if sum(n for f,n in key if FANS[f]['value']==2)==1 and sum(n for f,n in key if FANS[f]['value']==1)==6:
                silver.add(key)
    if len(seen)!=summary['combination_count']: raise ValueError('Summary count mismatch')
    if dict(sorted(counts.items()))!={int(f):n for f,n in summary['fan_distribution'].items()}:
        raise ValueError('Fan distribution mismatch')
    observations=set()
    for row in read_records(directory/'canonical_observations.jsonl'):
        result=evaluate(row['input'])
        if key_tuple(row['key'])!=key_tuple(result['canonical']['key']):
            raise ValueError('Invalid canonical observation')
        observations.add(key_tuple(row['key']))
    if len(observations)!=summary['canonical_count_observed']:
        raise ValueError('Canonical observation count mismatch')
    result={'passed':True,'policy':summary['policy'],'witnesses':len(seen),
            'complete':summary['complete'],'scope_complete':summary['scope_complete'],
            'gold_count':len(gold),'silver_count':len(silver),'max_fan_observed':max_fan,
            'fan_distribution':dict(sorted(counts.items())),
            'family_of_selected_witness':dict(families),
            'observed_closed':len(closed),'observed_opened':len(opened),
            'observed_ron':len(ron),'observed_tsumo':len(tsumo),
            'fan_presence':{str(f):{'combinations':n,'maximum_count':max_count[f]} for f,n in sorted(fan_counts.items())},
            'classification_complete':False}
    write_json(directory/'audit.json',result)
    return result

def report(directory):
    directory=Path(directory); data=audit(directory)
    summary=json.loads((directory/'summary.json').read_text())
    status='已穷尽当前配置的全部结构分区' if data['complete'] else (
        '所选分区已穷尽；不是完整国标总数' if data['scope_complete'] else '尚未穷尽；以下均为已确认的下界')
    lines=['# 国标麻将番种组合统计','',status+'。','',
        f"配置：`{summary['profile']}`；口径：`{summary['policy']}`。",'',
        f"已确认并复算 **{data['witnesses']}** 种组合。",'',
        f"金八番：{data['gold_count']}；银八番：{data['silver_count']}。它们只有在全量对应口径完成后才是总数。",'',
        '分类只记录当前见证所展示的门清性、和牌方式与结构，不能据此宣称另一种方式不可行。', '',
        '| 总番 | 组合数 |','|---:|---:|']
    lines.extend(f'| {f} | {n} |' for f,n in data['fan_distribution'].items())
    lines+=['','## 分区状态','','| 结构族 | 状态 |','|---|---|']
    lines.extend(f'| {f} | {s} |' for f,s in summary['partitions'].items())
    lines+=['','## 番种出现情况','','计分次数为同一番种的复计次数；以下统计当前已验证集合。','',
            '| 番种 | 番值 | 出现组合数 | 最大计分次数 |','|---|---:|---:|---:|']
    for fan, item in data['fan_presence'].items():
        fan=int(fan)
        name='箭刻' if fan==8058 else FANS[fan]['name']
        lines.append(f"| {name} | {FANS[fan]['value']} | {item['combinations']} | {item['maximum_count']} |")
    lines+=['','完成性限于当前有限结构及事件资源模型，不代表逐张牌山或服务器验证。',
            '规范计法必须独立搜索；全部最优投影的穷尽不证明规范投影已经穷尽。','']
    (directory/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    return data

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory');p.add_argument('--report',action='store_true')
    a=p.parse_args()
    try: data=(report if a.report else audit)(a.directory)
    except (ValueError,KeyError) as exc:p.exit(2,str(exc)+'\n')
    print(json.dumps(data,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
