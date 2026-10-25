"""Portable multi-process basis census, pause requests, merge and Python audit."""
import argparse
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from basis_backend import build
from decompose import parse
from enumerate_combinations import FAMILIES,write_json
from tools.basis_census import configuration,connect,fingerprint
from tools.native_census import dump,export
from tools.native_parallel import controller_lock


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def pair_rows(tiles):
    allowed=set(tiles);atoms=[]
    for t in tiles:
        atoms.append(Counter({t:3}))
        if t<27 and t%9<=6 and t+1 in allowed and t+2 in allowed:
            atoms.append(Counter({t:1,t+1:1,t+2:1}))
    return sum(max((a+b).values())<=4 for i,a in enumerate(atoms) for b in atoms[i:])


def prepare(output, *, tiles=tuple(range(34)), include_melds=True, rows_per_task=16,
            min_fan=8, max_fan=None):
    output=Path(output);tiles=tuple(sorted(set(tiles)))
    if rows_per_task<1 or min_fan < 0 or (max_fan is not None and max_fan < min_fan) or not tiles or any(type(t) is not int or not 0<=t<34 for t in tiles):
        raise ValueError('Invalid task scope')
    output.mkdir(parents=True,exist_ok=True)
    with controller_lock(output/'controller.lock'):
        path=output/'tasks.json'
        if path.exists():
            plan=json.loads(path.read_text(encoding='utf-8'))
            if (plan['source_sha256']!=fingerprint() or plan['tiles']!=list(tiles)
                    or plan['include_melds']!=include_melds
                    or plan.get('min_fan', 8) != min_fan
                    or plan.get('max_fan') != max_fan):
                raise ValueError('Existing basis plan source/scope mismatch')
            return plan
        if any(p.name!='controller.lock' for p in output.iterdir()):
            raise ValueError('Use a new basis output directory; never reuse old native production')
        P=pair_rows(tiles)
        tasks=[{'id':f'standard-{a:04d}-{min(a+rows_per_task,P):04d}',
                'family':'standard','left_begin':a,'left_end':min(a+rows_per_task,P)}
               for a in range(0,P,rows_per_task)]
        tasks=[{'id':f,'family':f,'left_begin':0,'left_end':None}
               for f in ('orphans','unconnected','knitted','seven_pairs')]+tasks
        plan={'backend':'basis-cpu-v1','source_sha256':fingerprint(),'tiles':list(tiles),
              'include_melds':include_melds,'min_fan':min_fan,'max_fan':max_fan,
              'pair_rows':P,'rows_per_task':rows_per_task,
              'tasks':tasks,'created_at':now()}
        write_json(path,plan)
        return plan


def summaries(output,plan):
    rows={}
    for task in plan['tasks']:
        p=output/'tasks'/task['id']/'summary.json'
        rows[task['id']]=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {
            'scope_complete':False,'bases':0,'physical':0,'contexts':0,
            'combination_count':0,'canonical_count':0,'termination':'not_started'}
    return rows


def status(output,plan,state,active,workers,reason=None,**extra):
    rows=summaries(output,plan)
    data={'backend':'basis-cpu-v1','state':state,'updated_at':now(),
          'controller_pid':os.getpid(),'worker_limit':workers,'reason':reason,
          'workers':[{'task':name,'pid':p.pid} for name,p in active.items()],
          'completed_tasks':sum(s['scope_complete'] for s in rows.values()),'task_count':len(rows),
          'bases':sum(s['bases'] for s in rows.values()),
          'physical':sum(s['physical'] for s in rows.values()),
          'contexts':sum(s['contexts'] for s in rows.values()),'tasks':rows,**extra}
    write_json(output/'RUN_STATUS.json',data)
    lines=['# 基础结构原生枚举状态','',f'更新时间（北京时间）：{data["updated_at"]}。状态：`{state}`。',
           '',f'完成任务：{data["completed_tasks"]}/{data["task_count"]}；工作进程：{len(active)}/{workers}。',
           '',f'基础结构：{data["bases"]:,}；声明与和牌张状态：{data["physical"]:,}；上下文：{data["contexts"]:,}。',
           '', '各任务组合可能重叠，局部组合数不相加。完整性以合并与独立复算通过为准。','']
    if reason:lines += [f'原因：{reason}','']
    tmp=output/'RUN_STATUS.md.tmp';tmp.write_text('\n'.join(lines),encoding='utf-8');tmp.replace(output/'RUN_STATUS.md')
    return data


def merge(output,plan,destination):
    """Validate exactly the manifest's full interval cover, then union witnesses."""
    destination=Path(destination)
    if destination.exists():raise ValueError('Merge destination already exists')
    if plan['source_sha256']!=fingerprint():raise ValueError('Source fingerprint changed')
    intervals=sorted((t['left_begin'],t['left_end']) for t in plan['tasks'] if t['family']=='standard')
    cursor=0
    for a,b in intervals:
        if a!=cursor or b is None or b<=a:raise ValueError('Incomplete or overlapping standard cover')
        cursor=b
    if cursor!=pair_rows(plan['tiles']):raise ValueError('Missing standard tail')
    special=[t['family'] for t in plan['tasks'] if t['family']!='standard']
    if sorted(special)!=sorted(f for f in FAMILIES if f!='standard'):raise ValueError('Missing/duplicate special family')
    # Validate all sources before creating a merged database.
    sources=[]
    for task in plan['tasks']:
        path=(output/'tasks'/task['id']/'census.sqlite3').resolve()
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as src:
            identity=json.loads(src.execute("SELECT value FROM metadata WHERE name='identity'").fetchone()[0])
            expected={'backend':'basis-cpu-v1','fingerprint':fingerprint(),
                      'config':configuration(task['family'],plan['tiles'],plan['include_melds'],
                                             task['left_begin'],task['left_end'],plan.get('min_fan',8),plan.get('max_fan'))}
            if identity!=expected:raise ValueError('Task source/scope mismatch: '+task['id'])
            progress=src.execute('SELECT family,complete FROM progress').fetchall()
            if progress!=[(task['family'],1)]:raise ValueError('Task is not exhausted: '+task['id'])
        sources.append(path)
    destination.mkdir(parents=True)
    conn=connect(destination/'census.sqlite3')
    try:
        for path in sources:
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as src,conn:
                conn.executemany('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',
                                 src.execute('SELECT * FROM observations'))
        complete=plan['tiles']==list(range(34)) and plan['include_melds']
        result={'backend':'basis-cpu-v1','source_sha256':fingerprint(),'scope_complete':True,
                'complete':complete,'tiles':plan['tiles'],'include_melds':plan['include_melds'],
                'min_fan':plan.get('min_fan',8),'max_fan':plan.get('max_fan'),
                'task_count':len(sources),'observation_count':conn.execute('SELECT count(*) FROM observations').fetchone()[0]}
        for policy,name in (('all_optimal','combination_count'),('canonical','canonical_count')):
            result[name]=conn.execute('SELECT count(DISTINCT key) FROM observations WHERE policy=?',(policy,)).fetchone()[0]
        with conn:conn.execute('INSERT INTO metadata VALUES (?,?)',('merged_scope',dump(result)))
        export(conn,destination);write_json(destination/'summary.json',result)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:conn.close()
    return result


def supervise(output,workers,slice_seconds):
    with controller_lock(output/'controller.lock'):
        plan=json.loads((output/'tasks.json').read_text(encoding='utf-8'))
        if plan['source_sha256']!=fingerprint():raise ValueError('Plan source fingerprint changed')
        specs={t['id']:t for t in plan['tasks']};active={}
        pending=deque(k for k,s in summaries(output,plan).items() if not s['scope_complete'])
        (output/'requests').mkdir(exist_ok=True);reason=None;failed=False
        try:
            while pending or active:
                stopping=(output/'stop.json').exists() or reason is not None
                if stopping and reason is None:reason='requested pause'
                if shutil.disk_usage(output).free<8*1024**3:stopping=True;reason='less than 8 GiB free disk space'
                if plan['source_sha256']!=fingerprint():stopping=failed=True;reason='source fingerprint changed'
                for name,process in list(active.items()):
                    code=process.poll()
                    if code is None:continue
                    del active[name]
                    done=summaries(output,plan)[name]['scope_complete']
                    if code not in (0,3) or (code==0 and not done):
                        stopping=failed=True;reason=f'{name} exited {code}; inspect its log'
                    elif not done:pending.append(name)
                if stopping:
                    for process in active.values():write_json(process.pause_file,{'requested_at':now()})
                    status(output,plan,'stopping',active,workers,reason)
                    if not active:
                        status(output,plan,'error' if failed else 'paused',{},workers,reason);return
                else:
                    while pending and len(active)<workers:
                        name=pending.popleft();task=specs[name];directory=output/'tasks'/name
                        pause=output/'requests'/f'{name}-{time.time_ns()}.json'
                        command=[sys.executable,'-u',str(ROOT/'tools/basis_census.py'),'--output',str(directory),
                                 '--family',task['family'],'--pause-file',str(pause),'--seconds',str(slice_seconds),
                                 '--batch-bases','16384','--batch-seconds','120',
                                 '--min-fan',str(plan.get('min_fan',8)),'--no-export']
                        if plan.get('max_fan') is not None:
                            command += ['--max-fan',str(plan['max_fan'])]
                        if plan['tiles']!=list(range(34)):
                            from decompose import compact
                            command+=['--tiles',compact(plan['tiles'])]
                        if not plan['include_melds']:command.append('--concealed-only')
                        if task['left_end'] is not None:command+=['--left-begin',str(task['left_begin']),'--left-end',str(task['left_end'])]
                        if (directory/'census.sqlite3').exists():command.append('--resume')
                        with (output/(name+'.log')).open('ab') as log:
                            process=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
                        process.pause_file=pause;active[name]=process
                    status(output,plan,'running',active,workers)
                if active:time.sleep(1)
            final=output/('merged-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
            status(output,plan,'merging',{},workers,final_directory=str(final))
            result=merge(output,plan,final)
            status(output,plan,'auditing',{},workers,final_directory=str(final))
            from tools.native_audit import audit
            from fast_runtime import install
            install();checked=audit(final);write_json(final/'witness-audit.json',checked)
            if not checked['passed']:raise ValueError('Python witness audit failed')
            status(output,plan,'complete' if result['complete'] else 'scope_complete',{},workers,
                   final_directory=str(final),combination_count=result['combination_count'],canonical_count=result['canonical_count'])
        except BaseException as exc:
            for process in active.values():write_json(process.pause_file,{'requested_at':now()})
            for process in active.values():process.wait()
            status(output,plan,'error',{},workers,str(exc));raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('prepare','start','stop','status','_supervise'))
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--workers',type=int,default=min(8,os.cpu_count() or 1))
    p.add_argument('--rows-per-task',type=int,default=16)
    p.add_argument('--slice-seconds',type=float,default=300)
    p.add_argument('--tiles')
    p.add_argument('--concealed-only',action='store_true')
    p.add_argument('--include-below-eight',action='store_true',
                   help='Enumerate only best explanations below 8 fan (0..7)')
    a=p.parse_args();output=a.output.resolve()
    if not 1<=a.workers<=(os.cpu_count() or 1) or a.slice_seconds<=0:p.error('Invalid worker count or time slice')
    if a.action=='status':print((output/'RUN_STATUS.json').read_text(encoding='utf-8'));return
    if a.action=='stop':write_json(output/'stop.json',{'requested_at':now()});print('Pause requested; wait for paused.');return
    if a.action=='_supervise':supervise(output,a.workers,a.slice_seconds);return
    build()
    min_fan=0 if a.include_below_eight else 8
    max_fan=7 if a.include_below_eight else None
    plan=prepare(output,tiles=parse(a.tiles) if a.tiles else tuple(range(34)),
                 include_melds=not a.concealed_only,rows_per_task=a.rows_per_task,
                 min_fan=min_fan,max_fan=max_fan)
    if a.action=='prepare':print(dump({'task_count':len(plan['tasks']),'pair_rows':plan['pair_rows']}));return
    with controller_lock(output/'controller.lock'):
        if (output/'stop.json').exists():(output/'stop.json').rename(output/f'stop-{time.time_ns()}.json')
    options={'creationflags':subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
    with (output/'controller.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,'-u',__file__,'_supervise','--output',str(output),
                                  '--workers',str(a.workers),'--slice-seconds',str(a.slice_seconds)],
                                 cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,**options)
    print(dump({'controller_pid':process.pid,'output':str(output)}))


if __name__=='__main__':main()
