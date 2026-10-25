# Windows 基础结构原生计番运行指南

## 一、适用范围与迁移

本指南用于当前 `basis-cpu-v1`：C++ 生成基础结构并计番，Python 保存组合见证和 checkpoint，完成后独立复算。

复制项目根目录的源码、`native/`、`tools/`、`tests/` 和所需文档。正式运行从空的结果目录开始；若要迁移正在运行的任务，须先安全暂停，再复制整个结果目录。不要在两台设备或同步盘上同时写同一个目录。

不要复制 `.venv/` 或任何 `build-*/` 目录；在 Windows 重新创建环境和二进制。使用压缩包或保留文件原始字节的复制方式，避免 Git 或编辑器转换换行导致指纹不匹配。

## 二、安装与校验

安装 64 位 Python 和支持 C++17 的编译环境。Visual Studio Build Tools 需选择 C++ 工作负载并安装 CMake；在 Developer PowerShell 运行。示例路径为本地 SSD 上的 `D:\Mahjong\guobiao_fan_combination`。

```powershell
Set-Location D:\Mahjong\guobiao_fan_combination
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe basis_backend.py
if ($LASTEXITCODE -ne 0) { throw '原生计番器构建失败' }

& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw '测试失败，暂不启动正式枚举' }
```

新路径本身只依赖 Python 标准库和 C++17；安装 `requirements.txt` 以运行完整回归测试。构建器优先尝试 `clang++`／`g++`，否则使用 CMake 的 Release 构建。macOS 本次验证不代表 Windows 已实机通过。

## 三、先做小域端到端验证

以下命令只遍历 `1234m` 受限牌域，自动合并并复算，不是正式全量任务：

```powershell
& .\.venv\Scripts\python.exe tools/basis_run.py start `
  --output results/basis-small-windows --tiles 1234m `
  --rows-per-task 4 --workers 8

& .\.venv\Scripts\python.exe tools/basis_run.py status `
  --output results/basis-small-windows
```

启动是后台方式，状态文件可能在控制器开始运行后才出现。等待状态为 `scope_complete`、工作进程列表为空，并确认最终目录的 `witness-audit.json` 中 `passed=true`。再次运行同一目录会从断点恢复，不需要删除文件。

## 四、正式 8 进程运行

以下示例使用全新目录：

```powershell
# 只准备任务布局，不执行全量遍历
& .\.venv\Scripts\python.exe tools/basis_run.py prepare `
  --output results/basis-full --rows-per-task 16

# 全部34种牌、全部声明，8个工作进程
& .\.venv\Scripts\python.exe tools/basis_run.py start `
  --output results/basis-full --workers 8 --slice-seconds 300

# 查看最新进度和控制器日志
& .\.venv\Scripts\python.exe tools/basis_run.py status `
  --output results/basis-full
Get-Content .\results\basis-full\controller.log -Tail 30
```

8 核 16 线程设备先使用 8 个工作进程；若内存和吞吐允许，可以暂停后改为 12 或 16 个。逻辑 CPU 使用率并不等于可用性能比例，是否增加进程应看实际基础结构和上下文吞吐。

时间片 300 秒用于任务轮换，不是全任务时限。每个原生批次默认约 5 秒或最多 4096 个基础结构，再提交一次 SQLite；内存缓存限制在当前基础结构，已知组合集合和数据库仍随发现的组合数增长。

## 五、暂停、续跑与调节并行度

```powershell
& .\.venv\Scripts\python.exe tools/basis_run.py stop `
  --output results/basis-full

& .\.venv\Scripts\python.exe tools/basis_run.py status `
  --output results/basis-full
```

等待状态为 `paused`、工作进程列表为空后再迁移或重启。原生批次会处理完当前基础结构，已提交批次保留；不要用强制结束进程代替正常暂停。

```powershell
# 恢复8进程；如需调整可将8改为12或16
& .\.venv\Scripts\python.exe tools/basis_run.py start `
  --output results/basis-full --workers 8
```

控制目录和任务目录的操作系统文件锁防止重复写入。异常断电后锁会释放；恢复前仍应确认没有残留控制器或工作进程。睡眠和关机会停止实际计算，后台进程不能跨关机继续。

## 六、输出和完成判据

| 路径 | 用途 |
| :---: | :---: |
| `tasks.json` | 源码指纹、完整计算范围与分片清单 |
| `RUN_STATUS.json`、`RUN_STATUS.md` | 控制器状态、活跃进程和已提交工作量 |
| `tasks/<任务>/census.sqlite3` | 权威断点、组合分类和见证；没有逐物理状态表 |
| `tasks/<任务>/known.bin` | 可由数据库重建的已知组合索引 |
| `<任务>.log` | 对应任务日志 |
| `merged-*/summary.json` | 去重后的组合统计与覆盖状态 |
| `merged-*/combinations.jsonl` | 去重后的组合分类见证 |
| `merged-*/witness-audit.json` | Python 独立复算结果 |

全域状态只有在五族穷尽、普通形覆盖完整、合并完成且独立复算通过后才为 `complete`。受限牌域只标 `scope_complete`。`physical` 是含重复的处理次数，分片组合数不能直接相加；中间摘要不是最终组合全集。

可用空间低于 8 GiB 时控制器请求安全暂停。新算法取消了此前约 190 GiB 的物理索引需求，但组合见证和各分片数据库仍占空间，不能宣称恒定磁盘占用。跨平台完整耗时以 Windows 实机验证为准。

macOS 对应命令只需将 `& .\.venv\Scripts\python.exe` 替换为 `.venv/bin/python`，其他参数相同。仓库不附带历史运行数据；如需复现，请使用全新输出目录。

公开仓库不附带已完成任务的分片；在 Windows 上应从源码创建新的输出目录并运行。
