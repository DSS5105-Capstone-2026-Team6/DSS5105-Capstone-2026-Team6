# dss5105 共享数据库：操作与验收

## 这次改动解决什么

网页与 Telegram 使用同一组数据库配置后，会读写同一个 PostgreSQL 数据库。
已确认的订单、排队增量、工坊表现和 API 调用次数因此可以跨进程共享。
没有配置云端地址时，程序继续使用本地 SQLite。云端连接失败会报错，不会
悄悄改写本地文件，避免两个入口各记各的账。

数据库名称与组织名称均为 dss5105。建表脚本位于 database/supabase_schema.sql。
它创建五张表，不导入旧记录。RLS 开启，浏览器匿名角色没有访问策略。
Python 服务器使用数据库连接凭据访问，不把数据库密码发给浏览器。

## 本地操作

1. 在 Supabase SQL Editor 执行建表脚本（当前项目已完成）。
2. Connect > Direct > Session pooler > URI，取得连接模板。
3. 在本地 .env 中填入 DISPATCH_DATABASE_URL 和 DISPATCH_DATABASE_PASSWORD。
   地址可以不含密码，将密码单独放在第二个配置项中即可，无需 URL 编码。
   .env 已被 Git 忽略，不要把它提交或放进交付压缩包。
4. 安装 pyproject.toml 的依赖，以及开发用的 pytest。
   当前工作副本已建立 .venv 并安装依赖。
5. 在项目根目录运行只读连接检查：

```powershell
.venv/Scripts/python.exe scripts/check_database.py
```

输出五张表的行数及 PASS，才能确认本机真的连到数据库。
这项检查不写订单，也不能单独证明网页与 Telegram 已部署连通。

## 自动验收

普通测试使用临时 SQLite，不访问云端，也不调用模型 API：

```powershell
.venv/Scripts/python.exe -m pytest -q
```

云端验收必须显式开启。它会在数据库中创建随机命名的测试 schema，
所有测试记录写在该 schema，结束后删除该测试 schema，不重置 public 中的应用表。
这一步需要当前连接有创建 schema 的权限：

```powershell
$env:DSS5105_RUN_CLOUD_TESTS = '1'
.venv/Scripts/python.exe -m pytest tests/test_shared_postgres.py -q
Remove-Item Env:DSS5105_RUN_CLOUD_TESTS
```

验收包含双客户端双向可见、排队一致、拒绝重复确认、拒绝过期建议、
并发只写一次、拆单失败回滚、工坊表现与调用次数共享、重置保留归档与预算。
客户端使用独立数据库连接，尚不等同于真实 Telegram 消息的端到端演示。

## 上线与手动演示

网页部署与机器人部署都需要这份代码和相同的数据库配置。
网页可在 Streamlit Secrets 中配置；机器人在运行环境变量或本地 .env 中配置。
机器人依赖文件也已加入 psycopg[binary]。
数据库地址不要用项目首页的 https API URL，要用 PostgreSQL pooler URI。

### 接入小组现有项目的顺序

1. 取得最新 GitHub 仓库代码，在独立分支合入本次修改，检查冲突并运行测试。
   本地工作副本来自之前的 ZIP，合入前需要核对此后的小组改动。
2. 由组员审核并合并修改，确认网页及机器人的实际部署分支都包含本次代码。
   README 写机器人部署在 Render；render.yaml 是 bot 分支的部署模板。
   部署模板不能证明实际机器人当前运行在哪里或使用哪个分支，上线前需核对。
3. 有网页管理权限的人在 Streamlit 的 Settings → Secrets 中追加下面两项，
   保留原有模型密钥、APP_PASSWORD 等设置，然后重新启动应用。

```toml
DISPATCH_DATABASE_URL = "postgresql://postgres.PROJECT_REF@POOLER_HOST:5432/postgres"
DISPATCH_DATABASE_PASSWORD = "YOUR_DATABASE_PASSWORD"
```

这里两行是模板；实际地址与密码从本地私有配置复制，在部署设置中填写。
4. 运行机器人的组员更新代码，在该电脑的 .env 或运行环境中配置同样两项，
   安装更新后的 adapter/requirements.txt，然后重启机器人。
   若实际已迁到 Render，则在该服务的 Environment 中填写同样两项并重新部署。
5. 两端分别运行连接检查，接着完成下面的双向人工确认演示。
   原本的本地 SQLite 历史记录保留在原处；本次云端账本从空记录开始。

数据库密码只填在私有配置或部署设置中。交给 GitHub 的改动不包含本机 .env。

在相同的订单/工坊数据、世界日期、stage 与 shock 设置下：

1. 网页请求并人工确认一张待分配订单，记录分配编号和工坊排队天数。
2. Telegram 查询同一张订单，确认已分配状态，尝试重复确认应失败。
3. Telegram 人工确认另一张订单，刷新网页 Records，检查新记录和排队天数。

网页需要刷新或交互后重新读取，当前没有自动实时推送。
各入口的对话、待确认建议、世界日期、shock 与场景开关仍由各自进程管理。
共享数据库不会自动同步这些设置，演示时必须对齐。
Reset demo 会影响同一数据库上的所有用户，仅在约定的演示环境中操作。

旧 SQLite 数据不会自动搬到云端。要迁移旧账本，应单独备份、检查订单重复，
并核对导入后的排队增量；本次从新建的空账本开始验收。

## 用白话解释关键保护

- version：你看到建议后如果别人已经安排了订单，原来的排队情况就变了。
  系统要求你先看更新后的建议，再确认。
- transaction：一次分配的检查和记账放在一起完成，失败就撤回这次写入。
- transaction lock：网页与 Telegram 同时记账时轮流处理，防止同时通过重复检查。
- UNIQUE order_id：数据库也禁止重复的分配键，作为额外保护。

## 完成状态的表述

分别记录建表、本地测试、云端验收、线上网页与 Telegram 演示的结果。
只有最后一步实际通过，才可以在展示中说“线上两端已连通”。

### 2026-11-10 本机验收记录

- Supabase 五张表已创建，只读连接检查通过。
- 离线测试：246 passed、6 skipped；其中 5 项云端测试需单独开启。
- 单独开启云端验收后：5 passed in 4.74s。
- 已验证独立连接之间双向读取分配、排队一致、重复及过期确认拦截、
  并发确认只写一次、拆单失败整体撤回、表现及调用预算共享、重置归档。
- 云端测试使用独立临时 schema，测试结束后清理；之后复查 public：
  allocations、performance、api_usage、allocation_archive 均为 0 行，
  ledger_meta 为 1 行。测试未向正式账本加入订单。
- 线上网页与真实 Telegram 的端到端部署演示尚未完成。

### 同日本机网页实际演示

- 使用本地 Streamlit 网页、个人 DeepSeek API 配置及真实 Supabase 数据库。
- 在第一个网页会话请求 ORD-063 的建议，点击 Confirm FreshStart (W8)，
  成功写入 A-0001：ORD-063 → W8，100 件，队列 0 → 1.02 天。
- 第二个独立网页会话重新加载后，在 Records 页读到同一条 A-0001，
  W8 队列也已更新；该会话的聊天记录仍为空，说明聊天没有随账本同步。
- 独立只读数据库检查确认 allocations 为 1 行。演示记录保留，未执行 Reset。
- 这是同一本机服务下的两个网页会话验证；尚未验证两个不同部署主机，
  小组线上 Streamlit 与真实 Telegram 也尚未更新接入。

### 同日独立测试 Telegram 机器人

- 用户通过 BotFather 创建 dss5105（@dss5105_test_bot），凭据只保存在本地私有配置。
- 机器人以独立 Python 进程运行，使用与本机网页相同的 Supabase 数据库。
- 用户在手机 Telegram 私聊发送 /start，收到欢迎回复。
- 用户询问 W8 当前队列，机器人返回 FreshStart 为 1.02 天，最近增加 1.02 天，
  与网页确认 A-0001 后的队列一致；已验证网页写入后的队列可经真实 Telegram 查询。
- 用户在 Telegram 请求分配 ORD-041，机器人推荐 W6；用户回复 yes 后，
  云数据库新增 A-0002：ORD-041 → W6，600 件，队列 1 → 5.73076923076923 天。
- 刷新本机网页，在 Records 页实际读到 A-0002 及原有 A-0001，完成真实
  Telegram 写入、网页读取的反向演示。两端运行在同一电脑的独立进程，
  使用真实云数据库；不等同于小组现有线上部署已接入。
- 重启与重复确认的补充验收见下节。
- 本次使用独立测试机器人；小组原有机器人和线上网页保持原样。

### 同日重复分配与进程重启验收

- 网页重新请求 ORD-041，展开卡片后显示：Already committed: A-0002 —
  ORD-041 → W6 — no further commit possible for this order，且不显示确认按钮。
- 独立进程调用实际 AuditLog.allocate，尝试将 ORD-041 再分给 W2，收到
  already committed / Refusing the duplicate commit。前后逐条记录内容的
  SHA-256 及所有工坊队列一致，账本仍为 2 条记录。
- 发现未修复的呈现问题：该重复请求的 AI 文案仍推荐 W2 并邀请回复 yes，
  与卡片的已分配提示冲突。分配被 UI 和数据库保护拦截，但对话文案需要改进；
  此次测试没有将该文案问题记为通过。
  （后续已修复：desk 在生成回复后检查账本，已分配的订单在回复开头标明
  "already committed"，推荐仅供参考；Telegram 只提供 skip 按钮，网页卡片
  提供 ⏭ Skip。见 tests/test_skip_and_duplicates.py。）
- 已停止并重新启动本机 Streamlit 服务和测试机器人进程，非仅刷新页面。
- 新机器人进程通过正式 _session_factory 创建 DispatchDesk，读回 2 条原有记录；
  W6=5.73076923076923、W8=1.02。重启后的网页 Records 也实际显示 A-0001/A-0002。
- 重启后再次检查全部分配记录内容及所有队列，与重启前完全一致。
- 用户在进程重启后，通过手机 Telegram 查询 W6 当前队列，机器人实际回复
  5.73 天、最近增加 4.73 天，与数据库及网页一致。用户提供截图确认收发成功，
  完成重启后的真实 Telegram 消息收发与数据持久性验证。
