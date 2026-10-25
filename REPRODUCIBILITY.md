# 复现实验

本仓库的目标是让读者从源码重建国标麻将番种组合统计。公开内容包括 C++ 原生枚举器、Python 计番器、事务调度器、测试、规则说明和轻量统计报告；完整运行数据库、分片、日志和编译产物不提交。

## 环境

- Python 3.9 或更高版本
- C++17 编译器；Windows 可使用 Visual Studio Build Tools 或 CMake
- `requirements.txt` 中的 Python 依赖主要用于旧求解器对照测试

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python basis_backend.py
.venv/bin/python -m unittest discover -s tests -v
```

## 运行

默认运行冻结的 `editor_no_flower_v1` 配置，覆盖四人、136 张、无花牌的五类基础结构：

```sh
.venv/bin/python tools/basis_run.py start \
  --output results/basis-reproduction \
  --workers 8
```

只枚举最佳总番为 $0\ldots7$ 的补充范围：

```sh
.venv/bin/python tools/basis_run.py start \
  --output results/basis-under-eight-reproduction \
  --workers 8 --include-below-eight
```

运行中可使用 `status` 查看进度、使用 `stop` 请求协作暂停；等待状态为 `paused` 且工作进程为空后，再用原命令恢复。每个任务把观测和游标写入同一 SQLite 事务，异常退出后只会重做未提交批次。

完成后生成报告：

```sh
.venv/bin/python tools/report_basis_results.py \
  --run results/basis-reproduction \
  --output reports/reproduced \
  --report REPORT_REPRODUCED.md \
  --distribution FAN_DISTRIBUTION_REPRODUCED.md
```

## 结果口径

基准运行的报告数字为全部同分最优 1,103,309 种、规范计法 1,097,951 种；补充的 0–7 番运行数字为 11,099 种和 11,053 种。二者分别对应不同的最佳总番筛选范围，不能把同一运行内的分类观测误当作自然牌局频率。完整算法和边界见 `BASIS_ENUMERATION.md`、`BASIS_VALIDATION.md` 与 `RULE_AUDIT.md`。

全量运行耗时、CPU 核数、磁盘占用和操作系统差异会影响复现时间；仓库中的历史耗时只作为本机 provenance，不是其他设备的性能承诺。
