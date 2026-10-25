# 本机运行记录与公开复现

本项目曾在 Apple M4 上完成两次全量基础结构枚举：

| 范围 | 全部同分最优 | 规范计法 | 观测记录 |
| :---: | :---: | :---: | :---: |
| 最佳总番至少8番 | 1,103,309 | 1,097,951 | 2,224,497 |
| 最佳总番0–7番 | 11,099 | 11,053 | 22,152 |

运行覆盖普通形、七对形、组合龙、全不靠、十三幺五类基础结构，共99个任务；每个任务使用事务 checkpoint，合并后由独立 Python 计番器复核。详细统计见 `REPORT.md`、`REPORT_UNDER_EIGHT.md` 及对应逐番分布表。

## 公开仓库的文件边界

完整 SQLite、JSONL、分片、日志、checkpoint 和构建目录已经清理，不随 Git 发布。`reports/` 中的 JSON 只保留轻量统计、最高番示例、差集和 SHA-256 provenance；其中记录的结果路径指向历史本机运行目录，不表示这些原始文件仍存在。

## 从零复现

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python basis_backend.py
.venv/bin/python -m unittest discover -s tests -v

.venv/bin/python tools/basis_run.py start \
  --output results/basis-reproduction \
  --workers 8
```

补充范围使用：

```sh
.venv/bin/python tools/basis_run.py start \
  --output results/basis-under-eight-reproduction \
  --workers 8 --include-below-eight
```

完成后可用 `tools/report_basis_results.py` 重新生成报告。Windows 的 PowerShell 命令见 [WINDOWS_BASIS.md](WINDOWS_BASIS.md)。

## 证据边界

这些数字证明当前冻结的有限结构、声明和事件模型下的组合存在性，不等同于实体手牌数量、自然牌局概率或完整四家牌谱的运行频率。历史运行时间仅是本机记录；其他设备应以实际吞吐量和磁盘空间为准。
