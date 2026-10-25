"""Run native census shards persistently on macOS or Windows.

Core scorer/generator sources are never modified. Existing validated SQLite
checkpoints are copied with the backup API before continuing production work.
"""
import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from enumerate_combinations import FAMILIES, write_json
from native_backend import build
from tools.native_census import fingerprint
from tools.native_parallel import controller_lock, task_specs, split_standard


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')


def summaries(output):
    rows = {}
    for spec in task_specs(output):
        path = output/spec['directory']/'summary.json'
        rows[spec['id']] = (json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
            'candidates':0,'generated':0,'contexts_evaluated':0,'combination_count':0,
            'canonical_count':0,'scope_complete':False,'termination':'not_started'})
    return rows


def seed(output, source):
    fp = fingerprint()
    # Validate every seed before creating the production directory.
    for family in FAMILIES:
        path = (source/family/'census.sqlite3').resolve()
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as conn:
            identity = json.loads(conn.execute(
                "SELECT value FROM metadata WHERE name='identity'").fetchone()[0])
            config = identity['config']
            if (identity['fingerprint'] != fp or config['families'] != [family]
                    or config['tiles'] != list(range(34)) or not config['include_melds']
                    or config['left_begin'] != 0 or config['left_end'] is not None
                    or config['min_fan'] != 8 or config['max_fan'] is not None
                    or not config['equivalent_winds']):
                raise ValueError('Seed checkpoint source/config mismatch: '+family)
    output.mkdir(parents=True, exist_ok=False)
    for family in FAMILIES:
        destination = output/family
        destination.mkdir()
        path = (source/family/'census.sqlite3').resolve()
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as src, \
             sqlite3.connect(destination/'census.sqlite3') as dst:
            src.backup(dst)
        shutil.copy2(source/family/'summary.json', destination/'summary.json')
    write_json(output/'run.json', {'created_at':now(), 'seed_root':str(source),
                                 'source_sha256':fp, 'scope':'all 34 tiles; all declarations; five families',
                                 'note':'seed validation runs are preserved; production checkpoints are independent'})


def save_status(output, state, active, reason=None, **extra):
    rows = summaries(output)
    specs = {s['id']:s for s in task_specs(output)}
    family_rows = {}
    for family in FAMILIES:
        members = [s for name,s in rows.items() if specs[name]['family'] == family]
        values = {k:sum(s[k] for s in members) for k in ('candidates','generated','contexts_evaluated')}
        values.update(scope_complete=all(s['scope_complete'] for s in members),
                      task_count=len(members),completed_tasks=sum(s['scope_complete'] for s in members),
                      combination_count=members[0]['combination_count'] if len(members) == 1 else None,
                      canonical_count=members[0]['canonical_count'] if len(members) == 1 else None,
                      combination_count_lower_bound=max(s['combination_count'] for s in members),
                      termination='exhausted' if all(s['scope_complete'] for s in members) else 'pending_or_running')
        family_rows[family] = values
    scheduler = json.loads((output/'scheduler.json').read_text()) if (output/'scheduler.json').exists() else {}
    data = {'state':state, 'updated_at':now(), 'controller_pid':os.getpid(),
            'reason':reason, 'worker_limit':scheduler.get('workers',8),
            'workers':[{'task':name,'family':specs[name]['family'],'pid':p.pid,
                        'pause_file':str(p.pause_file)} for name,p in active.items()],
            'families':family_rows,
            'tasks':{name:{k:s[k] for k in ('candidates','generated','contexts_evaluated',
                                           'combination_count','canonical_count','scope_complete','termination')}
                     for name,s in rows.items()}, **extra}
    write_json(output/'RUN_STATUS.json',data)
    lines = ['# 本机原生枚举运行状态', '', f'更新时间：{data["updated_at"]}。状态：`{state}`。', '',
             f'控制进程 PID：{os.getpid()}。工作进程上限：{data["worker_limit"]}。每批保存 SQLite checkpoint。', '']
    if reason:
        lines += [f'原因：{reason}', '']
    lines += ['| 结构族 | 已处理输入（分片合计） | 上下文 | 最优组合 | 规范组合 | 完成任务 | 活跃进程 |',
              '| :---: | :---: | :---: | :---: | :---: | :---: | :---: |']
    for family in FAMILIES:
        s = family_rows[family]
        count = sum(specs[name]['family'] == family for name in active)
        best = f'{s["combination_count"]:,}' if s['combination_count'] is not None else '待合并去重'
        canonical = f'{s["canonical_count"]:,}' if s['canonical_count'] is not None else '待合并去重'
        lines.append(f'| {family} | {s["candidates"]:,} | {s["contexts_evaluated"]:,} | '
                     f'{best} | {canonical} | {s["completed_tasks"]}/{s["task_count"]} | {count} |')
    lines += ['', '各族可能重叠，表中组合数不能相加作为全局总数。'
              '当前摘要仅包含已提交批次；运行中以各族 SQLite 为权威记录。', '']
    temporary = output/'RUN_STATUS.md.tmp'
    temporary.write_text('\n'.join(lines),encoding='utf-8')
    temporary.replace(output/'RUN_STATUS.md')
    return data


def supervise(output, *, workers=8, slice_seconds=300):
    # flock is released by the OS after a crash; stale PID files cannot permit
    # two controllers to write the same result directories.
    with controller_lock(output/'controller.lock'):
        _supervise(output,workers=workers,slice_seconds=slice_seconds)


def _supervise(output, *, workers, slice_seconds):
    expected = json.loads((output/'run.json').read_text())['source_sha256']
    if fingerprint() != expected:
        raise ValueError('Production checkpoint source fingerprint changed')
    stopping = False
    def request_stop(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT,request_stop)
    signal.signal(signal.SIGTERM,request_stop)
    if hasattr(signal,'SIGBREAK'):
        signal.signal(signal.SIGBREAK,request_stop)
    write_json(output/'scheduler.json',{'workers':workers,'slice_seconds':slice_seconds,'started_at':now()})
    (output/'requests').mkdir(exist_ok=True)
    specs = {s['id']:s for s in task_specs(output)}
    active = {}
    pending = deque(name for name,s in summaries(output).items() if not s['scope_complete'])
    reason = None
    failed = False
    save_status(output,'running',active)
    try:
        while pending or active:
            if (output/'stop.json').exists() or stopping:
                stopping = True
                reason = reason or 'requested pause'
            if shutil.disk_usage(output).free < 8*1024**3:
                stopping = True
                reason = 'less than 8 GiB free disk space'
            if fingerprint() != expected:
                stopping = True
                failed = True
                reason = 'core sources changed during enumeration'
            for family, process in list(active.items()):
                code = process.poll()
                if code is None:
                    continue
                del active[family]
                completed = summaries(output)[family]['scope_complete']
                if (code not in (0,3) and not stopping) or (code == 0 and not completed):
                    failed = stopping = True
                    reason = f'{family} exited with code {code}; inspect {family}.log'
                elif not completed:
                    pending.append(family)
            if stopping:
                for process in active.values():
                    if process.poll() is None and not getattr(process,'pause_requested',False):
                        write_json(process.pause_file,{'requested_at':now()})
                        process.pause_requested = True
                save_status(output,'stopping',active,reason)
                if not active:
                    save_status(output,'error' if failed else 'paused',active,reason)
                    return
            else:
                while pending and len(active) < workers:
                    family = pending.popleft()  # task id, not necessarily family name
                    spec = specs[family]
                    directory = output/spec['directory']
                    pause_file = output/'requests'/f'{family}-{time.time_ns()}.json'
                    command = [sys.executable,'-u',str(ROOT/'tools/native_worker.py'),
                               '--pause-file',str(pause_file),'--',
                               '--families',spec['family'],'--output',str(directory),
                               '--batch-size','256','--seconds',str(slice_seconds),'--no-export']
                    if (directory/'census.sqlite3').exists():
                        command.append('--resume')
                    if spec['left_end'] is not None:
                        command += ['--left-begin',str(spec['left_begin']),'--left-end',str(spec['left_end'])]
                    with (output/(family+'.log')).open('ab') as log:
                        active[family] = subprocess.Popen(command,cwd=ROOT,stdout=log,
                                                         stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
                    active[family].pause_file = pause_file
                save_status(output,'running',active)
            if active:
                time.sleep(2)
        # No generation limits are used. Reaching this point requires all
        # seeded families to finish, not merely expiration of one time slice.
        rows = summaries(output)
        if not all(s['scope_complete'] for s in rows.values()):
            raise RuntimeError('Queue finished without complete family coverage')
        destination = output/('merged-'+datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S'))
        save_status(output,'merging',{},final_directory=str(destination))
        with (output/'finalization.log').open('ab') as log:
            subprocess.run([sys.executable,str(ROOT/'tools/native_merge.py'),
                            *(str(output/s['directory']) for s in specs.values()),'--output',str(destination)],
                           cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
            save_status(output,'auditing',{},final_directory=str(destination))
            subprocess.run([sys.executable,str(ROOT/'tools/native_audit.py'),str(destination)],
                           cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        summary = json.loads((destination/'summary.json').read_text())
        audit = json.loads((destination/'witness-audit.json').read_text())
        if not summary['complete'] or not audit['passed']:
            raise RuntimeError('Final completeness/audit check failed')
        save_status(output,'complete',{},final_directory=str(destination),
                    combination_count=summary['combination_count'],canonical_count=summary['canonical_count'])
    except BaseException as exc:
        for process in active.values():
            if process.poll() is None:
                write_json(process.pause_file,{'requested_at':now()})
        # Wait for native workers to commit/rollback and finish their cleanup.
        for process in active.values():
            process.wait()
        save_status(output,'error',{},str(exc))
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('start','status','stop','prepare','_supervise'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seed-root',type=Path,default=ROOT/'results/native-validation/smoke')
    p.add_argument('--workers',type=int,default=min(8,os.cpu_count() or 1))
    p.add_argument('--rows-per-task',type=int,default=16)
    p.add_argument('--slice-seconds',type=int,default=300)
    a = p.parse_args()
    output = a.output.resolve()
    if a.slice_seconds <= 0:
        p.error('--slice-seconds must be positive')
    if a.workers < 1 or a.workers > (os.cpu_count() or 1):
        p.error('--workers must be between 1 and the number of logical CPUs')
    if a.action == '_supervise':
        supervise(output,workers=a.workers,slice_seconds=a.slice_seconds)
    elif a.action == 'status':
        print((output/'RUN_STATUS.json').read_text())
    elif a.action == 'stop':
        write_json(output/'stop.json',{'requested_at':now(),'reason':'requested pause'})
        print('Pause requested; wait for RUN_STATUS.json to report paused.')
    elif a.action == 'prepare':
        if not output.exists():
            seed(output,a.seed_root.resolve())
        plan = split_standard(output,rows_per_task=a.rows_per_task)
        print(json.dumps({'task_count':len(plan['tasks']),'pair_rows':plan['pair_rows'],
                          'preserved_cursor':plan['original_cursor']},ensure_ascii=False))
    else:
        if not output.exists():
            seed(output,a.seed_root.resolve())
        if fingerprint() != json.loads((output/'run.json').read_text())['source_sha256']:
            raise ValueError('Production checkpoint source fingerprint changed')
        # Check the same OS lock before clearing a past stop request.
        with controller_lock(output/'controller.lock'):
            if (output/'stop.json').exists():
                (output/'stop.json').rename(output/('stop-'+str(time.time_ns())+'.json'))
        if not (output/'tasks.json').exists() and not summaries(output)['standard']['scope_complete']:
            split_standard(output,rows_per_task=a.rows_per_task)
        build()
        launch_options = ({'creationflags':subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                          if os.name == 'nt' else {'start_new_session':True})
        with (output/'controller.log').open('ab') as log:
            process = subprocess.Popen([sys.executable,'-u',__file__,'_supervise','--output',str(output),
                                        '--workers',str(a.workers),'--slice-seconds',str(a.slice_seconds)],
                                       cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL,**launch_options)
        print(json.dumps({'controller_pid':process.pid,'output':str(output)},ensure_ascii=False))


if __name__ == '__main__':
    main()
