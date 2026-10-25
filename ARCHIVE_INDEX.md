# 实验产物清理说明

本项目公开仓库只保留文档、源码、测试、示例和轻量统计报告。完整 SQLite/JSONL 结果、99 个分片、日志、checkpoint、旧方案快照及本地编译目录均属于可再生实验产物，已从工作树清理，未纳入 Git。

## 保留内容

| 内容 | 用途 |
| :---: | :---: |
| `REPORT.md`、`FAN_DISTRIBUTION.md` | 八番及以上基准统计与逐番分布 |
| `REPORT_UNDER_EIGHT.md`、`FAN_DISTRIBUTION_UNDER_EIGHT.md` | 最佳总番 0–7 番补充统计 |
| `reports/` | 轻量 JSON 统计、最高番示例、差集和 SHA-256 provenance |
| `native/`、`basis_backend.py`、`tools/` | 可复现的枚举、调度、合并、报告和审计代码 |
| `tests/`、`examples/` | 回归测试、跨语言差分和示例输入 |

## 不随仓库发布的内容

- `results/` 下的 SQLite、JSONL、分片、日志和运行状态；
- `archive/` 下的旧算法、旧报告快照和历史中间数据；
- `.venv/`、`build-*`、缓存和平台相关二进制。

这些内容会占用数 GiB 至数十 GiB，但都可以用当前源码重新生成。重新运行必须使用全新输出目录，不要把旧平台或旧算法的 checkpoint 复制进当前任务。
