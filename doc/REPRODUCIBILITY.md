# 复现与跨平台运行

## 环境

需要 Python 3.9 或更高版本、C++17 编译器和 CMake；完整回归测试安装 `requirements.txt`。运行目录、虚拟环境和 `build-*` 目录不应提交到 Git。

macOS/Linux：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python basis_backend.py
.venv/bin/python -m unittest discover -s tests -v
```

Windows Developer PowerShell：

```powershell
Set-Location D:\Mahjong\guobiao_fan_combination
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe basis_backend.py
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 小域验证与全量运行

先用受限牌域确认编译、调度、合并和见证复算：

```sh
.venv/bin/python tools/basis_run.py start \
  --output results/basis-small --tiles 1234m --rows-per-task 4 --workers 8
.venv/bin/python tools/basis_run.py status --output results/basis-small
```

确认状态为 `scope_complete` 且工作进程为空后，再使用全新目录执行全量：

```sh
.venv/bin/python tools/basis_run.py start \
  --output results/basis-full --workers 8
```

Windows 将 Python 路径替换为 `.venv\Scripts\python.exe`。8 核 16 线程设备先从 8 个进程开始，暂停后再根据内存和吞吐调整到 12 或 16 个。

## 暂停、恢复与报告

```sh
.venv/bin/python tools/basis_run.py stop --output results/basis-full
.venv/bin/python tools/basis_run.py status --output results/basis-full
.venv/bin/python tools/basis_run.py start --output results/basis-full --workers 8
```

等待状态为 `paused` 且工作进程为空后才能迁移或恢复。源码、配置和范围指纹变化会拒绝继续使用断点。完整运行完成后，可用报告工具读取新的结果目录：

```sh
.venv/bin/python tools/report_basis_results.py \
  --run results/basis-full \
  --output reports/reproduced \
  --report REPORT_REPRODUCED.md \
  --distribution FAN_DISTRIBUTION_REPRODUCED.md
```

发布条件是五族覆盖完整、合并通过、所有见证独立复算通过且状态为 `complete`。跨平台耗时、内存和磁盘占用需在目标设备实测。
