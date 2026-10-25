"""Finish the current eight-worker census: merge, audit, classify and package.

This is a one-shot local batch controller, not a scheduled notification service.
Unknown/interrupted/failed workers stop completion rather than publish totals.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enumerate_combinations import fingerprint, write_json

ROOT = Path(__file__).resolve().parents[1]
INTERVALS = ('8-15','16-31','32-63','64-up')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', default='results')
    parser.add_argument('--pid-manifest', help='Optional worker-name to PID JSON for crash detection')
    args = parser.parse_args()
    results = Path(args.results).resolve()
    results.mkdir(parents=True, exist_ok=True)
    workers = [results/'bands'/(policy+'-'+interval)
               for policy in ('all_optimal','canonical') for interval in INTERVALS]
    pids = json.loads(Path(args.pid_manifest).read_text()) if args.pid_manifest else {}
    logs = results/'completion-logs'
    logs.mkdir(exist_ok=True)

    def status(phase, states=None, message=None):
        state = {'phase': phase, 'complete': phase == 'complete',
                 'updated_unix': time.time(), 'source_sha256': fingerprint(),
                 'message': message, 'workers': states or []}
        write_json(results/'RUN_STATUS.json', state)
        lines = ['# 本次全量运行状态', '', '阶段：`'+phase+'`。', '',
                 '只有`complete`阶段才表示全量搜索、见证复算、条件展开复算和可行性分类均完成。', '']
        if message:
            lines += [message, '']
        if states:
            lines += ['| 区间任务 | 已保存组合数 | 区间完成 | 状态 |', '|---|---:|---|---|']
            for row in states:
                lines.append(f"| {row['name']} | {row['count']} | {'是' if row['complete'] else '否'} | {row['termination']} |")
            lines += ['', '各任务也保存复算时发现的区间外最佳组合，彼此可能重叠，以上数量不能直接相加。', '']
        if phase == 'complete':
            lines += ['最终综述：[overview/REPORT.md](overview/REPORT.md)。', '',
                      '结果与证明记录压缩包：[final-results.zip](final-results.zip)。', '']
        else:
            lines += ['详细日志保存在`completion-logs/`；搜索仍未完成时不报告全局最终总数。', '']
        tmp = results/'STATUS.md.tmp'
        tmp.write_text('\n'.join(lines), encoding='utf-8')
        tmp.replace(results/'STATUS.md')
        print(json.dumps({'phase': phase, 'message': message}), flush=True)

    def command(arguments, log_name):
        with (logs/log_name).open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable]+list(map(str,arguments)), cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True)

    try:
        while True:
            states = []
            for worker in workers:
                data = json.loads((worker/'summary.json').read_text())
                if data['source_sha256'] != fingerprint():
                    raise RuntimeError('Rule/model fingerprint changed: '+worker.name)
                complete = data['domain_complete']
                if not complete and data['termination'] != 'running':
                    raise RuntimeError(worker.name+': '+data['termination'])
                if not complete and worker.name in pids:
                    try:
                        os.kill(pids[worker.name],0)
                    except ProcessLookupError:
                        raise RuntimeError('Worker exited without completion: '+worker.name)
                states.append({'name':worker.name,'count':data['combination_count'],
                               'complete':complete,'termination':data['termination']})
            status('search',states)
            if all(row['complete'] for row in states):
                break
            time.sleep(10)
        command(['-m','unittest','discover','-s','tests','-q'],'tests.log')
        for policy,name in (('all_optimal','all-optimal'),('canonical','canonical')):
            directories=[results/'bands'/(policy+'-'+interval) for interval in INTERVALS]
            output=results/name
            status('merge',message='合并 '+policy)
            command(['tools/merge_bands.py',*directories,'--output',output],name+'-merge.log')
            status('audit',message='复算 '+policy+' 的全部见证与已排除物理输入')
            command(['audit_results.py',output,'--report'],name+'-audit.log')
            command(['tools/audit_inventory_expansions.py','--source',output,
                     '--output',output/'inventory-audit.json',*directories],name+'-inventory-audit.log')
            classification=results/('classifications-'+name)
            status('classification',message='完成 '+policy+' 的门清性与和牌方式分类')
            command(['tools/classify_combinations.py',output,'--output',classification,
                     '--timeout-ms','0'],name+'-classification.log')
            command(['tools/audit_classifications.py',classification,'--source',output],
                    name+'-classification-audit.log')
        status('overview')
        command(['tools/build_overview.py','--all-optimal',results/'all-optimal',
                 '--canonical',results/'canonical','--output',results/'overview',
                 '--classifications-all',results/'classifications-all-optimal',
                 '--classifications-canonical',results/'classifications-canonical'],'overview.log')
        chosen=[results/name for name in ('all-optimal','canonical','overview','classifications-all-optimal',
                                          'classifications-canonical','final-gold','final-gold-all-optimal',
                                          'final-silver','final-silver-all-optimal')]+workers
        status('package')
        with zipfile.ZipFile(results/'final-results.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
            for directory in chosen:
                for path in sorted(directory.rglob('*')):
                    if path.is_file():
                        archive.write(path,path.relative_to(results))
        with zipfile.ZipFile(results/'final-results.zip') as archive:
            bad=archive.testzip()
            if bad:
                raise RuntimeError('Archive CRC mismatch: '+bad)
        status('complete',message='全部统计、复算与分类完成，综述和压缩包已保存。')
    except Exception as exc:
        status('error',message=str(exc))
        raise


if __name__=='__main__':
    main()
