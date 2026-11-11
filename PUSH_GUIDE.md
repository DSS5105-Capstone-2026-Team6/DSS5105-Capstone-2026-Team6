# 推送须知（Push Guide）

给新会话或新协作者的提交规则。仓库是 Track 2 Dispatch Desk 的完整可运行版本，
默认分支 `main`，所有改动通过分支 + Pull Request 合并。

## 仓库结构

| 目录 | 内容 |
|---|---|
| `desk/` | 应用核心：工具、分配器、路由、账本、学习产能 |
| `app/` | Streamlit 网页（按界面拆分：theme / components / tabs / rail / sidebar） |
| `adapter/` | Telegram bot（`adapter/requirements.txt` 是 bot 部署用的依赖） |
| `eval/` | 评估：`run_eval.py`（调用模型）、`score_run.py`（评分）、`replay_offline.py`（离线回放）、`shock.py` |
| `harness/` | 课程共享模拟器 `simulate.py`（**永不修改**）+ 基准与算法实验 |
| `data/` | 订单、工坊、50 条聊天请求 + 标签、120 条时间线请求 + 标签 |
| `tests/` | pytest 测试，全部离线运行 |
| `docs/` | 算法、评估、部署、共享数据库、拆单、失败案例分析 |
| `database/` | Supabase 建表脚本 |
| `notebooks/` | 120 条时间线 + shock 评估 |
| `results/` | 只提交 `inbox_*` / `heldout_*` 的运行结果和分数，其余被 `.gitignore` 忽略 |

依赖只有一份：根目录 `pyproject.toml`（`uv sync` 安装，含 dev 组的 pytest 和
matplotlib）。`uv.lock` 不入库。

## 禁止提交

- `.env`、`.streamlit/secrets.toml`、任何 API key 或数据库密码
- `*.sqlite3` 本地账本、`results/` 下除上述以外的运行输出
- 个人笔记、课程其他作业、数据备份

`.gitignore` 会忽略 `*.json`。`data/` 下新增的标签文件要用 `git add -f` 明确加入。

## 代码约定

- 模型不做算术：所有数字来自工具输出，回复里的数字要能在 tool log 里找到（faithfulness）。
- 模型工具只读；提交分配只能经过人工确认（网页卡片 / bot 按钮 / yes）。
- 聊天侧（4 月 1 日快照）和模拟器（1 月 1 日起）是两个独立状态，工具层不得混用。
- 新功能至少带一个失败用例测试。
- 测试文件顶部加 sys.path 引导，方便直接运行：

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

## 提交流程

```bash
git switch -c <type>/<short-name>
```

```bash
uv run pytest -q
```

测试必须全绿。只 `git add` 点名的文件，不用 `git add -A` 或 `git add .`。

```bash
git add <files>
```

```bash
git commit -m "English title" -m "bullet points of what changed"
```

```bash
git push -u origin <type>/<short-name>
```

然后在 GitHub 上开 Pull Request 合并到 `main`。CI（`.github/workflows/tests.yml`）
会在 Python 3.11 和 3.12 上跑同一套测试。
