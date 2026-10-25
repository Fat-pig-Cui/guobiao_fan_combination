# guobiao_fan_combination

国标麻将番种计数组合的理论枚举、独立 Python 计番与见证复算。

八番及以上的基准全量计算已完成：全部同分最优计法 **1,103,309 种**，规范计法 **1,097,951 种**。另有独立任务只枚举最佳总番为 $0\ldots7$ 的组合，用于补充总番低于8番的集合，得到全部同分最优 **11,099 种**、规范计法 **11,053 种**。与八番及以上结果合并后，两个口径分别为 **1,114,408** 和 **1,109,004** 种；低番结果写入独立报告，不覆盖基准结果。

结论适用于冻结的 `editor_no_flower_v1` 配置：四人、136 张、无花牌，其中明暗杠为 5 番，天地人和各为 8 番。统计番种名称及其计分次数，不统计实体手牌种数或出现概率；有限资源及事件模型没有构造完整四家牌谱。详细口径与边界见 [正式报告](REPORT.md)。

## 文档导航

| 文档 | 内容 |
| :---: | :---: |
| [REPORT.md](REPORT.md) | 全量结论、分类、最高番示例、耗时与验证边界 |
| [FAN_DISTRIBUTION.md](FAN_DISTRIBUTION.md) | 逐番分布、番种覆盖及两种计法差集 |
| [ALL_FAN_SCOPE.md](ALL_FAN_SCOPE.md) | 纳入总番低于8番组合的口径、运行方式与验证边界 |
| [REPORT_UNDER_EIGHT.md](REPORT_UNDER_EIGHT.md) | 最佳总番0–7番的新增组合统计 |
| [FAN_DISTRIBUTION_UNDER_EIGHT.md](FAN_DISTRIBUTION_UNDER_EIGHT.md) | 0–7番逐番分布和番种覆盖 |
| [BASIS_ENUMERATION.md](BASIS_ENUMERATION.md) | 当前算法：基础结构共享分析、原生计番与断点 |
| [BASIS_VALIDATION.md](BASIS_VALIDATION.md) | 跨语言差分、断点测试与代表性性能验证 |
| [BASIS_LOCAL_RUN.md](BASIS_LOCAL_RUN.md) | 历史运行记录、统计摘要和公开复现方式 |
| [REPRODUCIBILITY.md](REPRODUCIBILITY.md) | 从零安装、运行、暂停恢复和重新生成报告 |
| [WINDOWS_BASIS.md](WINDOWS_BASIS.md) | Windows 构建、多进程运行、暂停与恢复 |
| [RULE_AUDIT.md](RULE_AUDIT.md) | 冻结规则与参考计番实现的差异 |
| [ARCHIVE_INDEX.md](ARCHIVE_INDEX.md) | 可删除归档的内容、体积和删除影响 |

## 当前实现

推荐路径为 `basis-cpu-v1`。C++ 按普通形、七对形、组合龙、全不靠、十三幺五族遍历基础结构，共享拆分、听牌和顺子关系分析，再枚举声明、和牌张、事件及风位。Python 保存新增组合见证及事务游标，合并后使用独立计番器逐条复算。

同时收集全部同分最优与规范计法，以及门清／副露、荣和／自摸分类。没有以“发现的组合已经足够多”作为停止条件，也没有采用未经证明的花色对称剪枝。

旧 Z3、手写生成器、CUDA 筛选器及旧原生工具源码保留作对照；其方案、运行说明及历史产物已归档，不属于当前推荐运行流程。

## 安装与验证

Python 3.9 以上及 C++17 编译器。依赖中包含旧求解器及对照测试使用的 Z3。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python basis_backend.py
.venv/bin/python -m unittest discover -s tests -v

# 独立计番
.venv/bin/python calc_fan.py examples/silver_arrow.json
```

Windows 的编译器安装及 PowerShell 命令见 [Windows 指南](WINDOWS_BASIS.md)。

## 统计报告与复现

仓库只提交文档、源码、测试和轻量机器可读统计；完整 SQLite、JSONL、分片日志和运行检查点不随仓库发布，以避免把数十 GiB 的实验产物带入 Git。`REPORT.md`、`FAN_DISTRIBUTION.md` 是八番及以上基准结果，`REPORT_UNDER_EIGHT.md`、`FAN_DISTRIBUTION_UNDER_EIGHT.md` 是最佳总番 0–7 番的补充结果。报告中的路径和 SHA-256 是当时本机运行的 provenance，不表示原始数据库仍包含在仓库中。

安装依赖并运行完整测试：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python basis_backend.py
.venv/bin/python -m unittest discover -s tests -v
```

使用新目录重新生成实验数据和报告：

```sh
.venv/bin/python tools/basis_run.py start \
  --output results/basis-reproduction \
  --workers 8

# 只枚举最佳总番 0–7 番
.venv/bin/python tools/basis_run.py start \
  --output results/basis-under-eight-reproduction \
  --workers 8 --include-below-eight

.venv/bin/python tools/report_basis_results.py \
  --run results/basis-reproduction \
  --output reports/reproduced \
  --report REPORT_REPRODUCED.md \
  --distribution FAN_DISTRIBUTION_REPRODUCED.md
```

枚举支持事务 checkpoint、暂停和恢复；Windows 的 PowerShell 流程见 [Windows 指南](WINDOWS_BASIS.md)，算法边界见 [基础结构枚举说明](BASIS_ENUMERATION.md)。完整实验通常需要较长时间和较大的临时磁盘空间，不应在 Git 工作树中提交 `results/`、`build-*` 或虚拟环境。

## 启动新的枚举

已有任务已经完成，重新枚举应使用新的输出目录。默认从 8 个工作进程开始，Windows 8 核 16 线程设备可暂停后调整到 12／16 个进程。

```sh
.venv/bin/python tools/basis_run.py start --output results/basis-new-run --workers 8
.venv/bin/python tools/basis_run.py status --output results/basis-new-run
.venv/bin/python tools/basis_run.py stop --output results/basis-new-run
```

等待状态为 `paused` 且工作进程列表为空后，使用相同 `start` 命令恢复。源码指纹或配置不同会拒绝使用旧断点。每个事务提交完整基础结构的观测和游标，中断后可重做尚未提交的批次。

## 数据清理策略

完整运行数据库、分片、日志和历史归档已从本地工作树移除；这些文件属于可再生实验产物。仓库保留报告数字、统计 JSON、示例和源码，因此任何人都可以从零重建，而无需下载本机的数十 GiB 中间数据。`.gitignore` 会阻止新的运行产物进入版本库。
