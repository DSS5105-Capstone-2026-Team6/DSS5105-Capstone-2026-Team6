# 推送须知（Push Guide）

给任何新会话/新协作者：本仓库是**精简的 Track 2 项目**，本地工作目录比仓库大得多（含课程其他作业、数据备份、个人笔记）。推送前务必按本文件操作，防止本地目录和 repo 打架。

## 核心原则

1. **仓库 = Track 2 最小可运行集**：`data/ harness/ agent/ tests/ README.md pyproject.toml pytest 配置`。
2. **本地目录 = 超集**：课程其他作业（KAGGLE/ Week3ML/ W2&5Langc/ 等）、`Track 1 and Track 2 Data/`、个人笔记，全部**不入库**。
3. **提交前必须 `git status` 过一遍**，只 `git add` 点名的文件，禁止 `git add -A` / `git add .`。

## 双 pyproject 机制（最重要）

- **本地根目录 `pyproject.toml`**：完整版依赖（pandas/langchain/…），**永远不提交**，`git status` 里常年显示 `M`，属正常。
- **`release/pyproject.toml`**：推送版的唯一真源（精简依赖）。改推送版依赖只改这个文件。
- 同步到仓库（不碰本地文件）：

```bash
BLOB=$(git hash-object -w release/pyproject.toml)
git update-index --cacheinfo 100644,$BLOB,pyproject.toml
```

之后 `git status` 显示 `MM pyproject.toml`（已暂存推送版 + 工作区本地版），属预期状态。

## 推送清单

**入库**：`agent/`、`tests/`、`harness/`（纯代码改动）、`README.md`、`data/` 的官方文件、`release/pyproject.toml`（按上面机制注入索引）

**留在本地（禁止提交）**：
- `.env`（API key，已被 gitignore，提交前仍须确认）
- `results/`（跑批输出）、`uv.lock`、`release/` 目录本身
- `harness/` 里的**中文学习注释**（本地标注，不入库——`git diff harness/` 检查，只暂存纯逻辑改动）
- `system.png`、`KAGGLE/`、`Track 1 and Track 2 Data/`、`docs/`、`src/`、`notebooks/` 等课程遗留

## 代码范式（新文件必须遵守）

- **库文件**（agent/ 等）：末尾带冒烟入口；包内相对导入 + 直跑回退：

```python
try:
    from .xxx import ...
except ImportError:  # run directly as a script
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.xxx import ...

if __name__ == "__main__":
    ...  # 演示核心功能，不放系统逻辑
```

- **测试文件**（tests/）：顶部 sys.path 引导（在 `from agent...` 之前）+ pytest 入口：

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
```

- 测试必须含**每个工具至少一个失败用例**（Sprint 2 评分项）。

## 提交流程

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q   # 必须全绿才提交
git add <点名的文件>                               # 禁止 -A
git commit -m "英文标题 + 要点列表"
git push origin main
```

## 其他约定

- `harness/simulate.py` **永不修改**（共享评估装置）。
- 聊天态队列（4 月 1 日快照）与模拟器态队列（1 月 1 日）是两个独立状态，工具层不得混用。
- LLM 不做算术；所有数字必须来自工具输出；tool log 需保留供 faithfulness checker 使用。
- 推送目标是 `origin`（DSS5105-Capstone-2026-Team6），私有库。
