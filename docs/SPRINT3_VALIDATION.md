# Sprint 3 规划、验收与测试记录

负责人：Xuehann · XuantingWang（README "Planning, validation and testing"）
基线：`spr3` 分支 = `main` @ `18ccf99`（PR #55 合并后），2026-11-10。

本文件分四部分：任务计划表、共享账本验收、UI 验收清单、自动测试与发现的问题。
"✅ 通过 / ❌ 不通过 / ⏳ 待测"只按实际做过的检查填写，没做过的不写通过。

---

## 1. Sprint 3 任务计划表

| # | 工作项 | 负责人 | PR | 合并日期 | 状态 |
|---|---|---|---|---|---|
| 1 | 拆单 + held-out 评审三个问题修复 | Claude · SishuoZhou | #20 | 10-31 | ✅ 已合并 |
| 2 | UI：hybrid 默认、队列条/动画、Dashboard 三视图、世界时钟 + shock | Zhangruikai | 直接提交 | 10-31 起 | ✅ 已合并 |
| 3 | 120 单全量时间线评估（shock 窗口） | Zhangruikai | 直接提交 | — | ✅ 已合并 |
| 4 | 一键派单：LLM parser 修复、卡片即确认、自动滚动、已分配标记、Group chat 改名 | Claude · SishuoZhou | #22–#35 | 11-09 | ✅ 已合并 |
| 5 | 场景预览：周日停工 / 运输延迟 / 产能噪声 / 日期控件 | GuanmingYang | #21、#36、#53→#54 撤回→#55 | 11-09 – 11-10 | ✅ 已合并 |
| 6 | 共享 Supabase PostgreSQL 账本 | RuoxiZhou | #38 | 11-10 | ✅ 已合并，线上接入见 §2 |
| 7 | 前端重组、bot 增强、连接池/缓存/pipeline、LLM 超时、批量确认、沙盒模式 | kimi | #37、#39–#45 | 11-10 | ✅ 已合并 |
| 8 | README Sprint 3 章节 | kimi | #46、#48–#50 | 11-10 | ✅ 已合并 |
| 9 | 规划、验收、测试（本文件） | Xuehann · XuantingWang | — | 11-10 | 🔄 进行中 |

---

## 2. 共享账本上线验收

依据：[SHARED_DATABASE.md](SHARED_DATABASE.md) 的验收步骤、`scripts/check_database.py`、
`tests/test_shared_postgres.py`。前五项的详细过程见 SHARED_DATABASE.md 的 2026-11-10 记录。

| 验收项 | 状态 | 证据 |
|---|---|---|
| Supabase 五张表创建，`check_database.py` 只读检查 PASS | ✅ | SHARED_DATABASE.md 11-10 本机记录 |
| 云端自动验收（`DSS5105_RUN_CLOUD_TESTS=1`）：双向可见、重复/过期确认拦截、并发只写一次、拆单回滚、预算共享、重置归档 | ✅ 5 passed | 同上 |
| 本机两个网页会话：会话 1 确认 ORD-063 → A-0001，会话 2 的 Records 可读 | ✅ | 同上 |
| 本机测试 bot 确认 ORD-041 → A-0002，网页 Records 可读（反向） | ✅ | 同上 |
| 重复分配被 UI 与数据库双重拦截；进程重启后记录与队列一致 | ✅ | 同上 |
| **小组线上 Streamlit + 正式 Telegram bot 接入共享库的端到端演示** | ⏳ | 待测，步骤见下 |

### 线上端到端演示（待做）

前提：线上网页 Secrets 与 bot 运行环境都已配置 `DISPATCH_DATABASE_URL` /
`DISPATCH_DATABASE_PASSWORD`；网页在 Records 页点 **Reset & connect to shared DB**
（默认是本地沙盒，不连接共享库）；两端世界日期、stage、shock 设置一致。

| 步骤 | 操作 | 预期 | 结果 | 截图 |
|---|---|---|---|---|
| 1 | 两端分别运行 `scripts/check_database.py` | 都输出 PASS | | |
| 2 | 线上网页请求并确认一张待分配订单 | 生成 A-xxxx，工坊排队天数增加 | | |
| 3 | 正式 bot 查询同一订单，并尝试再次确认 | 显示已分配；再次确认被拒绝 | | |
| 4 | 正式 bot 确认另一张订单 | 生成新记录 | | |
| 5 | 刷新线上网页 Records | 看到第 4 步的记录，排队天数一致 | | |

只有第 5 步通过，展示时才能说"线上两端已连通"。

---

## 3. UI 改动验收清单

在线上网页或本地 `streamlit run app/streamlit_app.py` 上逐项操作。
每项写结果和截图文件名（建议放 `docs/validation/` 下）。

| # | 功能 | 来源 | 操作 | 预期 | 结果 | 截图 |
|---|---|---|---|---|---|---|
| U1 | hybrid 是默认目标 | Zhangruikai | 新会话打开 Desk | 右侧 Re-rank objective 高亮 hybrid | ✅ 初始页截图可见 | |
| U2 | 世界时钟切换 | Zhangruikai | Start date 在 April 1st / January 1st 间切换 | 页面重建，队列与订单随日期变化 | ⏳ | |
| U3 | 种子 shock | Zhangruikai | Shock seed 5105 → Trigger shock；再 Resolve | 同一种子总是停同一工坊；推荐结果随之变化；恢复后还原 | ⏳ | |
| U4 | 候选卡片：队列条 + 入场动画 | Zhangruikai | Sample inbox → Dispatch | 每张卡片有实时队列条和入场动画 | ⏳ | |
| U5 | Dashboard 三视图 | Zhangruikai | 切到 Dashboard | queue timeline、allocator lens、capacity drift 都能显示 | ⏳ | |
| U6 | 点卡片即确认 | #30 | 点一张候选卡片 | 直接提交，生成分配记录 | ⏳ | |
| U7 | 确认后滚到下一单 | #31–#33 | 连续确认，含跳过一单 | 平滑滚到最近的未处理订单（下方优先，否则上方） | ⏳ | |
| U8 | 已分配订单标记 | #27 | 对已分配订单重新请求 | 显示 "Already committed: …"，不显示确认按钮 | ⏳ | |
| U9 | LLM parser 标签页 | #22、#23、#28、#29 | LLM parser → Parse → Dispatch | 一次点击即可解析；字段与订单登记表核对 | ⏳ | |
| U10 | Group chat 标签名 | #35 | 看输入方式标签 | 显示 Group chat（不是 Paste） | ✅ 初始页截图可见 | |
| U11 | 场景预览 | #21、#34、#36、#55 | Open scenario preview | 默认折叠；周日停工、运输延迟、产能噪声、日期控件可调，并与基线排名对比 | ⏳ | |
| U12 | 批量确认 | #44 | 多单待确认时点 Confirm all open | 全部提交；失败项单独报错 | ⏳ | |
| U13 | 沙盒模式 | #45 | 新会话打开 Records | 默认本地沙盒；Reset & connect to shared DB 后切到共享库 | ⏳ | |
| U14 | Bot 一键确认 + yes all | #39、#44 | Telegram 请求两单，点按钮 / 回复 yes all | 按钮确认成功；yes all 一次提交全部 | ⏳ | |
| U15 | Bot `/queue` 图表 | #39 | Telegram 发 `/queue` | 返回队列柱状图 | ⏳ | |
| U16 | Bot 提议重启后保留 | #39 | 请求后重启 bot，再回复 yes | 原提议仍可确认 | ⏳ | |

---

## 4. 自动测试与发现的问题

### 4.1 测试结果（2026-11-10，`spr3` @ 18ccf99）

```bash
uv run pytest tests -q
```

| 时间点 | 结果 |
|---|---|
| 修复前 | 266 passed、**2 failed**、6 skipped |
| 修复后（本次提交） | **268 passed**、6 skipped、136 subtests passed（共 274 个） |

6 个 skip：5 个是需要显式开启的云端测试（`tests/test_shared_postgres.py`），
1 个是学习模型下 ORD-063 在 W6 不是紧余量场景（`tests/test_adaptive_tools.py:85`）。

### 4.2 发现的问题

| # | 问题 | 影响 | 状态 |
|---|---|---|---|
| F1 | `matplotlib` 只在 `adapter/requirements.txt`，不在 `pyproject.toml`；按项目方式安装后 `test_queue_chart_png_*` 两个测试失败 | 本地/CI 测试变红；线上 bot 不受影响（Render 装的是 adapter/requirements.txt） | ✅ 已修：加入 dev 依赖组 |
| F2 | README 写 "267 tests"，实际 274 | 文档数字过时 | ✅ 已修 |
| F3 | 对已分配订单再次请求时，AI 回复仍推荐别的工坊并邀请回复 yes，和卡片上的 "Already committed" 提示矛盾。`desk/desk.py` 的 `handle_message` 在调用 LLM 前没有检查账本 | 不会产生重复分配（UI 和数据库都会拦截），但回复会误导调度员 | ❌ 未修复，需交给 desk 负责人 |
| F4 | 线上两端尚未完成端到端演示（§2） | 展示时不能说"线上已连通" | ⏳ 待测 |
