"""Publish statistics from a completed, audited basis census, read-only."""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
from itertools import groupby
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from calc_fan import evaluate
from decompose import compact,parse
from enumerate_combinations import write_json
from rules import PROFILE,FANS,describe,fan_total
from tools.basis_census import fingerprint
from tools.basis_coverage import verify_coverage

POLICIES=('all_optimal','canonical')
LABELS={'overall':'全部','closed':'门清','opened':'副露','ron':'荣和','tsumo':'自摸',
        'closed_ron':'门清荣和','closed_tsumo':'门清自摸',
        'opened_ron':'副露荣和','opened_tsumo':'副露自摸'}
MASKS={'overall':15,'closed':12,'opened':3,'ron':5,'tsumo':10,
       'closed_ron':4,'closed_tsumo':8,'opened_ron':1,'opened_tsumo':2}


def dump(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def md(path,lines):
    # Human-readable output; no modifications to source census artifacts.
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')


def table(headers,rows):
    return ['| '+' | '.join(headers)+' |','| '+' | '.join(':---:' for _ in headers)+' |']+[
        '| '+' | '.join(str(v) for v in row)+' |' for row in rows]


def notation(data):
    groups=[]
    for meld in data['melds']:
        tiles=parse(meld['tiles'])
        if meld['kind']=='ankan':tiles=tiles+(tiles[0],) if isinstance(tiles,tuple) else list(tiles)+[tiles[0]]
        groups.append(compact(tiles))
    return data['hand']+data['win']+(' '+''.join(groups) if groups else '')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--distribution',type=Path,required=True)
    a=p.parse_args();root=a.run.resolve();a.output=a.output.resolve()
    status=json.loads((root/'RUN_STATUS.json').read_text())
    plan=json.loads((root/'tasks.json').read_text())
    launch_path=root/'launch.json'
    launch=json.loads(launch_path.read_text()) if launch_path.exists() else {'started_at':plan.get('created_at',status['updated_at'])}
    final=Path(status['final_directory']);summary=json.loads((final/'summary.json').read_text())
    audit=json.loads((final/'witness-audit.json').read_text())
    min_fan=int(plan.get('min_fan',summary.get('min_fan',8)))
    max_fan=plan.get('max_fan',summary.get('max_fan'))
    assert status['state']=='complete' and not status['workers']
    assert summary['complete'] and summary['scope_complete'] and audit['passed'] and not audit['errors']
    assert int(summary.get('min_fan',min_fan))==min_fan
    assert summary.get('max_fan',max_fan)==max_fan
    assert plan['source_sha256']==summary['source_sha256']==fingerprint()
    assert plan['tiles']==list(range(34)) and plan['include_melds']
    assert status['completed_tasks']==status['task_count']==len(plan['tasks'])==99
    intervals=sorted((t['left_begin'],t['left_end']) for t in plan['tasks'] if t['family']=='standard')
    end=0
    for low,high in intervals:assert low==end;end=high
    assert end==plan['pair_rows']==1506
    assert sorted(t['family'] for t in plan['tasks'] if t['family']!='standard')==sorted(('seven_pairs','orphans','unconnected','knitted'))
    coverage_audit=verify_coverage(root,status,plan)
    populations=Counter()
    for task in plan['tasks']:
        s=status['tasks'][task['id']]
        assert s['scope_complete'] and s['termination']=='exhausted'
        assert s['identity']['fingerprint']==fingerprint()
        assert s['identity']['config']['profile']==PROFILE
        populations[task['family']]+=s['bases']
    assert sum(populations.values())==status['bases']==28009420
    a.output.mkdir(parents=True,exist_ok=True)
    if (a.output/'statistics.json').exists():raise ValueError('Use a new report output directory')
    conn=sqlite3.connect((final/'census.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True)
    stats={pol:{'counts':Counter(),'observations':0,'distribution':{label:Counter() for label in LABELS},
                'fan_presence':Counter(),'fan_max_count':Counter(),'topics':Counter(),
                'intersections':Counter(closed_and_opened=0,ron_and_tsumo=0)} for pol in POLICIES}
    differences=Counter();unique=0
    with (a.output/'only_all_optimal.jsonl').open('w',encoding='utf-8') as diff:
        for text,items in groupby(conn.execute('SELECT key,policy,closed,method,total FROM observations ORDER BY key'),key=lambda r:r[0]):
            key=json.loads(text);total=fan_total(key);masks={pol:0 for pol in POLICIES};unique+=1
            for _,policy,closed,method,value in items:
                assert total==value and total>=min_fan and (max_fan is None or total<=max_fan)
                bit=(4 if closed else 1)*(2 if method=='tsumo' else 1)
                masks[policy]|=bit;stats[policy]['observations']+=1
            assert not (masks['canonical']&~masks['all_optimal']),('canonical category missing',key)
            for policy,mask in masks.items():
                if not mask:continue
                s=stats[policy]
                for label,bits in MASKS.items():
                    if mask&bits:s['counts'][label]+=1;s['distribution'][label][total]+=1
                if mask&12 and mask&3:s['intersections']['closed_and_opened']+=1
                if mask&5 and mask&10:s['intersections']['ron_and_tsumo']+=1
                for fan,count in key:
                    s['fan_presence'][fan]+=1;s['fan_max_count'][fan]=max(s['fan_max_count'][fan],count)
                if total==8:
                    if all(FANS[f]['value']==1 for f,n in key):s['topics']['gold']+=1
                    if sum(n for f,n in key if FANS[f]['value']==2)==1 and sum(n for f,n in key if FANS[f]['value']==1)==6:
                        s['topics']['silver']+=1
            if masks['all_optimal'] and not masks['canonical']:
                differences[total]+=1
                diff.write(dump({'key':key,'total':total,'fans':describe(key)})+'\n')
    assert unique==summary['combination_count']==stats['all_optimal']['counts']['overall']
    assert summary['canonical_count']==stats['canonical']['counts']['overall']
    assert sum(s['observations'] for s in stats.values())==summary['observation_count']==audit['observations_checked']
    assert sum(differences.values())==summary['combination_count']-summary['canonical_count']
    assert sum(s['intersections']['closed_and_opened'] for s in stats.values())==0
    if min_fan>=8:
        assert stats['all_optimal']['topics']=={'gold':26,'silver':711}
        assert stats['canonical']['topics']=={'gold':26,'silver':699}
    for pol,s in stats.items():
        assert sum(s['counts'][v] for v in ('closed_ron','closed_tsumo','opened_ron','opened_tsumo'))==s['observations']
        assert s['counts']['closed']+s['counts']['opened']==s['counts']['overall']
        assert s['counts']['ron']+s['counts']['tsumo']-s['intersections']['ron_and_tsumo']==s['counts']['overall']
        for label,hist in s['distribution'].items():assert sum(hist.values())==s['counts'][label]
    print('Grouped all observations; invariants and independent topic totals passed.',flush=True)
    maxima=[]
    for closed,method in ((1,'ron'),(1,'tsumo'),(0,'ron'),(0,'tsumo')):
        top=conn.execute('SELECT max(total) FROM observations WHERE policy=? AND closed=? AND method=?',('all_optimal',closed,method)).fetchone()[0]
        text,total,evidence=conn.execute('SELECT key,total,evidence FROM observations WHERE policy=? AND closed=? AND method=? AND total=? LIMIT 1',('all_optimal',closed,method,top)).fetchone()
        data=json.loads(evidence)['input'];result=evaluate(data);key=json.loads(text)
        assert result['total']==total and key in [r['key'] for r in result['optimal']]
        maxima.append({'closed':bool(closed),'method':method,'total':total,'key':key,'input':data,
                       'notation':notation(data),'fans':describe(key),'independently_rescored':True})
    conn.close()
    write_json(a.output/'maxima.json',maxima)
    began=datetime.fromisoformat(launch['started_at']);finished=datetime.fromisoformat(status['updated_at'])
    merge_at=datetime.strptime(final.name,'merged-%Y%m%d-%H%M%S').replace(tzinfo=timezone.utc).astimezone(began.tzinfo)
    export_at=datetime.fromtimestamp((final/'summary.json').stat().st_mtime,tz=began.tzinfo)
    times={'started_at':began.isoformat(),'merged_stage_started_at':merge_at.isoformat(),
           'export_finished_at_approx':export_at.isoformat(),'finished_at':finished.isoformat(),
           'total_seconds':(finished-began).total_seconds(),
           'enumeration_seconds_approx':(merge_at-began).total_seconds(),
           'merge_export_seconds_approx':(export_at-merge_at).total_seconds(),
           'audit_seconds_approx':(finished-export_at).total_seconds(),
           'note':'launch.json timestamp is a few seconds after actual controller start; phase times use UTC merged directory timestamp and summary file mtime'}
    artifacts=[]
    for filename in ('census.sqlite3','combinations.jsonl','summary.json','witness-audit.json'):
        path=final/filename;h=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(4*1024*1024),b''):h.update(chunk)
        artifacts.append({'file':str(path.relative_to(ROOT)),'bytes':path.stat().st_size,'sha256':h.hexdigest()})
    report={'profile':PROFILE,'complete':True,'source_sha256':fingerprint(),'run':str(root.relative_to(ROOT)),
            'min_fan':min_fan,'max_fan':max_fan,
            'final_directory':str(final.relative_to(ROOT)),'coverage':dict(populations),
            'processed':{k:status[k] for k in ('bases','physical','contexts','completed_tasks','task_count')},
            'timing':times,'policies':stats,'only_all_optimal_count':sum(differences.values()),
            'only_all_optimal_distribution':differences,'only_canonical_count':0,'audit':audit,
            'artifacts':artifacts,'report_checks':{'coverage_and_checkpoints':True,'classification_invariants':True,
            'canonical_observations_subset':True,'gold_silver_regression':True,'four_maxima_rescored':True},
            'coverage_verification_mode':coverage_audit['verification_mode'],
            'boundary':'Frozen no-flower editor profile and finite inventory/event model; no complete four-player action history or official universal rules claim'}
    write_json(a.output/'statistics.json',report)
    write_json(a.output/'artifacts.json',artifacts)
    write_json(a.output/'timing.json',times)
    max_total=max(max(hist) for s in stats.values() for hist in s['distribution'].values() if hist)
    write_distribution(a.distribution,stats,differences,min_fan,max_total)
    write_report(a.report,report,maxima,a.output,min_fan,max_total,Path(a.distribution).name,max_fan)
    print(dump({'report':str(a.report),'statistics':str(a.output/'statistics.json'),
                'counts':{p:dict(s['counts']) for p,s in stats.items()},'timing':times,'maxima':[(x['closed'],x['method'],x['total']) for x in maxima]}),flush=True)


def write_distribution(path,stats,differences,min_fan=8,max_total=324):
    lines=['# 国标麻将番种组合：逐番分布','','配置为 `editor_no_flower_v1`，全部五族穷尽且分类观测通过独立复核。',
           '每格是该总番下可实现的不同番种次数向量数量，不是手牌出现频率。门清包含暗杠；同一向量可以同时支持荣和、自摸，故两列不宜直接相加。','']
    labels=('overall','closed','opened','closed_ron','closed_tsumo','opened_ron','opened_tsumo')
    for pol,title in (('all_optimal','一、全部同分最优计法'),('canonical','二、规范计法')):
        s=stats[pol];lines+=['## '+title,'']
        rows=[[total]+[f"{s['distribution'][label][total]:,}" for label in labels] for total in range(min_fan,max_total+1)]
        rows.append(['合计']+[f"{s['counts'][label]:,}" for label in labels])
        lines+=table(['总番']+[LABELS[label] for label in labels],rows)+['']
    lines+=['## 三、番种的组合覆盖','','下表统计包含某番种的不同组合数量，每种组合只计一次；复计上限另列。箭刻三个牌种合并统计。两种计法的列都按各自全局组合去重，不能解释为自然发生概率。','']
    rows=[]
    for fan,definition in FANS.items():
        if fan in (8059,8060):continue
        rows.append(['箭刻' if fan==8058 else definition['name'],definition['value'],
                     f"{stats['all_optimal']['fan_presence'][fan]:,}",f"{stats['canonical']['fan_presence'][fan]:,}",
                     stats['all_optimal']['fan_max_count'][fan],stats['canonical']['fan_max_count'][fan]])
    lines+=table(['番种','单项番值','全部最优组合数','规范组合数','全部最优最大复计','规范最大复计'],rows)+['']
    lines+=['## 四、仅全部最优计法中存在的组合','','这里只列至少存在一个差异组合的总番；完整差集以次数向量保存。','']
    lines+=table(['总番','差异组合数'],[[t,f'{differences[t]:,}'] for t in sorted(differences)])+['']
    md(path,lines)


def write_report(path,r,maxima,output,min_fan=8,max_total=324,distribution_name='FAN_DISTRIBUTION.md',max_fan=None):
    stats=r['policies'];n=lambda x:f'{x:,}'
    lines=['# 国标麻将番种组合全量枚举报告','','## 一、统计结论','',
           f"**在本报告冻结的无花编辑器规则及有限事件模型下，全部同分最优计法共有 {n(stats['all_optimal']['counts']['overall'])} 种番种计数组合，规范计法共有 {n(stats['canonical']['counts']['overall'])} 种。**",
           f"{r['processed']['task_count']} 个任务全部穷尽；合并后的 {n(sum(s['observations'] for s in stats.values()))} 条分类观测逐条通过独立 Python 计番复核，错误数为零。完整流程耗时约 {timedelta(seconds=round(r['timing']['total_seconds']))}。",'',
           '## 二、统计口径','',
           '配置为 `editor_no_flower_v1`：四人、136 张、无花牌；采用项目冻结的传统番种目录，其中明暗杠为 5 番，天地人和各为 8 番。该结果不能直接推广到其他平台或所有称为“国标”的规则变体。',
           f'一个组合由“番种名称及其计分次数”确定。例如一般高计两次与一般高计一次是不同组合。白、发、中对应的箭刻合并为同一名称，最终投影有 84 个维度；物理判定仍区分实际牌种。本报告收录最佳解释总番在 {min_fan}～{max_fan if max_fan is not None else "无上限"} 范围内的和牌。','',
           '- **全部同分最优**：对一个完整输入，保留所有达到最高总番的番种次数向量，再对全部输入取并集。',
           '- **规范计法**：每个完整输入仅保留固定优先级选出的最高番向量。顺子小番依一般高、喜相逢、连六、老少副的次序处理平局，等待番依边张、坎张、单钓将处理，其余按固定原始番种次数序比较；最后再合并箭刻名称。','',
           '同一组合的不同花色、实体牌编号、牌形或座次不另计。结果是组合种类数量，不是实体手牌数量、和牌概率或自然对局频率。','',
           '## 三、组合总数与分类','']
    rows=[]
    for label in LABELS:rows.append([LABELS[label]]+[n(stats[p]['counts'][label]) for p in POLICIES])
    rows.append(['分类观测记录']+[n(stats[p]['observations']) for p in POLICIES])
    lines+=table(['范围','全部同分最优','规范计法'],rows)+['']
    lines+=['门清指没有吃、碰、明杠，暗杠仍属于门清。副露分类只要存在吃、碰或明杠即成立。分类来自完整声明和事件枚举保存的观测，不是只看每个组合首个见证推断。',
            '在本配置下，门清与副露组合交集为零；荣和与自摸可以支持同一组合，重叠量如下。因此不能将全部荣和数与全部自摸数直接相加。','']
    lines+=table(['集合关系','全部同分最优','规范计法'],[
        ['门清与副露交集']+[n(stats[p]['intersections']['closed_and_opened']) for p in POLICIES],
        ['荣和与自摸交集']+[n(stats[p]['intersections']['ron_and_tsumo']) for p in POLICIES]])+['']
    lines+=[f"规范组合全部属于全部最优集合。仅全部最优集合中存在 {n(r['only_all_optimal_count'])} 种，仅规范集合存在 0 种。差异表示该向量虽然能够成为同分最佳解释，却从未成为本规则固定优先级下的规范结果。",'',
            '## 四、总番分布与最高番','']
    bands=tuple((lo,min(hi,max_total)) for lo,hi in ((min_fan,7),(8,15),(16,31),(32,63),(64,127),(128,255),(256,324)) if lo<=max_total and lo<=min(hi,max_total))
    lines+=table(['总番范围','全部同分最优','规范计法'],[
        [f'{lo}～{hi}']+[n(sum(v for t,v in stats[p]['distribution']['overall'].items() if lo<=t<=hi)) for p in POLICIES]
        for lo,hi in bands])+['']
    mode=max(stats['all_optimal']['distribution']['overall'],key=stats['all_optimal']['distribution']['overall'].get)
    lines+=[f"总番范围为 {min_fan}～{max_total} 番。按组合种类计算，{mode} 番的组合最多：全部同分最优为 {n(stats['all_optimal']['distribution']['overall'][mode])} 种。完整逐番、门清／副露及和牌方式分布见 [分布表]({distribution_name})。",'']
    lines+=table(['类别','最高番','举例牌型','计分项'],[
        [('门清' if x['closed'] else '副露')+('荣和' if x['method']=='ron' else '自摸'),x['total'],
         '`'+x['notation']+'`','＋'.join(f"{f['name']}{'×'+str(f['count']) if f['count']>1 else ''}（{f['subtotal']}）" for f in x['fans'])]
        for x in maxima])+['']
    lines+=['牌型先写和牌前手牌，紧接独立的和牌张代码，空格后写固定面子；暗杠用五个相同数字作显示标记，明杠用四个。这里只是文档表示法，实际输入仍用四张牌表示杠。','',
            '上表四例均为东场东家。荣和例取海底捞月；自摸例取牌墙已空时的杠后补牌，依本配置同时计妙手回春与杠上开花。四例均无额外外部公开牌、无首巡事件。完整输入见报告数据目录的 `maxima.json`，四个示例本次又分别调用 Python 计番器复算通过。', '',
            '## 五、八番专题回归','',
            '金八番指八个 1 番计分项；银八番指一个 2 番计分项加六个 1 番计分项，均以实际复计次数累计。此次从全量最佳向量重新筛选，结果与此前独立专题结论一致。','']
    lines+=table(['专题','全部同分最优','规范计法'],[[name]+[stats[p]['topics'][topic] for p in POLICIES] for topic,name in (('gold','金八番'),('silver','银八番'))])+['',
            '## 六、算法、覆盖与验证','',
            '先枚举一般形与四类特殊形的有限基础结构，再共享同一基础结构的全部拆分、固定面子几何及听牌分析。C++ 枚举全部合法声明、和牌张和事件／风位，比较所有解释并输出新增观测；Python 在同一 SQLite 事务中提交观测与游标。',
            '普通形由二面子表连接，95 个连续区间完整覆盖 1506 行。特殊族各有一个完整任务。没有用“已发现组合数量足够多”作为停止条件，没有进行未经证明的花色或序数对称剪枝。','']
    names={'standard':'四面子一般形','seven_pairs':'七对形','knitted':'组合龙形','unconnected':'全不靠形','orphans':'十三幺形'}
    lines+=table(['基础结构族','处理数'],[[names[f],n(r['coverage'][f])] for f in names])+['']
    lines+=[f"总计处理 {n(r['processed']['bases'])} 个基础结构、{n(r['processed']['physical'])} 次声明与和牌张状态、{n(r['processed']['contexts'])} 个计番上下文。不同基础结构可重复覆盖相同物理状态，故后两项不是互异牌型数量。",'',
            ('本次整理使用保留的任务元数据核对任务清单、完成状态、源指纹、范围和已提交游标。' if r['coverage_verification_mode']=='retained_checkpoint_metadata' else '本次整理再次从 99 个任务的原始数据库检查源指纹、范围和已提交游标。')+
            '此外核对普通形区间覆盖、规范观测包含关系、分类并集／交集恒等式、逐番分布求和和八番专题回归。此前测试有 61 项通过；全量保留的 2,224,497 条分类观测已由结构拆分和计番分别实现的 Python 检查器逐条复算，数据库完整性检查为 `ok`。','',
            '完整性的依据是有限生成循环、合法声明／事件覆盖和分片穷尽；正例复核只证明已保存见证通过检查，本身不能证明无遗漏。当前结论仍受冻结计番规则及其资源／有限时序模型约束，没有构造四家从配牌到和牌的完整牌谱，也不以本次离线复核声称经过服务器验证。','',
            '## 七、实际运行耗时','']
    t=r['timing'];duration=lambda seconds:str(timedelta(seconds=round(seconds)))
    lines+=table(['阶段','北京时间或耗时'],[
        ['启动记录',t['started_at']],['枚举结束、进入合并',t['merged_stage_started_at']],
        ['完成全部复核',t['finished_at']],['枚举阶段约',duration(t['enumeration_seconds_approx'])],
        ['合并与导出约',duration(t['merge_export_seconds_approx'])],['Python 独立复核约',duration(t['audit_seconds_approx'])],
        ['完整流程约',duration(t['total_seconds'])]])+['',
            '阶段时刻依据控制器记录、最终目录时间戳和摘要文件修改时间，阶段耗时按近似值列出。设备与并发度以实际运行记录为准。','',
        '## 八、结果与复现','',
        f"正式任务目录为 `{r['run']}/`，最终结果为 `{r['final_directory']}/`。`summary.json` 保存总数，`combinations.jsonl` 保存组合分类及见证，`census.sqlite3` 保存合并后的查询表，`witness-audit.json` 保存完整独立复核结论。",'',
        f"本报告的机器可读统计保存在 `{output.resolve().relative_to(ROOT)}/statistics.json`，最高番示例为 `maxima.json`，两种计法的全局差集为 `only_all_optimal.jsonl`，结果文件大小和 SHA-256 见 `artifacts.json`。",'',
        '报告生成器只读取当前运行目录中的数据库和完成状态；这些原始运行产物不属于公开仓库，报告发布时只保留轻量统计摘要。', '',
        '重新生成同口径报告：','', '```sh',
        '.venv/bin/python tools/report_basis_results.py \\',
        '  --run results/basis-reproduction \\',
        '  --output reports/reproduced \\',
        '  --report REPORT_REPRODUCED.md \\',
        '  --distribution FAN_DISTRIBUTION_REPRODUCED.md','```','',
        '生成工具只读正式数据库，并校验完成状态、源指纹、分片范围和计数恒等式；重新复算四个最高番示例，不重复进行耗时的全量枚举。报告工具只处理当前 basis-cpu-v1 结果格式。','']
    md(path,lines)


if __name__=='__main__':main()
