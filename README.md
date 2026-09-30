# VeriEnv 最小实现实验：GitHub → Amazon

本仓库固定生成输入、任务与确定性 verifier，检查 **环境生成、浏览器关键交互、验证结果稳定性**。不是会议材料，也不是完整站点视觉复刻。

## 已检查的上游流程

固定上游：[kyle8581/VeriEnv @ f3a43895e0e496ac0c7435f69a92c7c94c05fa0d](https://github.com/kyle8581/VeriEnv/tree/f3a43895e0e496ac0c7435f69a92c7c94c05fa0d)。

| 阶段 | 上游入口 | 实際行为与本实验处理 |
|---|---|---|
| 生成 | `00_cursor_command.sh` / `prompt.yaml` | 读取截图与端口配置，通过 `cursor-agent` / `gpt-5.2` 实现站点。这里沿用该 CLI，改为版本控制中的固定功能规格。 |
| 修复 | `01_cursor_bug_report.sh` / `bug_report.yaml` | 运行、找错、修复。这里保留首次失败，不自动修复污染首次结果；修改后必须用新的运行目录重新生成。 |
| 任务 | `02_cursor_task_generation.sh` / `instruction_generation_and_validation.yaml` | 生成任务及 SDK 验证。这里将任务提前固定，独立 verifier 不由生成模型改写。 |

上游 shell 在 agent 命令后执行 `echo`，没有 fail-fast，因此其脚本退出码不能可靠代表生成成功。本骨架直接调用 agent、记录退出码/超时，且检查产物。上游要求截图和全站实现；这里没有可用参考截图，所以明确采用**功能最小规格**，不能据此判断视觉保真度。没有复用预生成环境来冒充生成结果。

## 固定输入与任务

| 顺序 | 输入 | 任务 | 独立判据 |
|---|---|---|---|
| 1 | `inputs/github.json` | 搜索 `demo/agent-lab`，打开详情，创建标题 `Repro issue`、正文 `Fixed experiment` 的 issue | 仓库不变，持久状态中恰好存在一个完全匹配 issue |
| 2 | `inputs/amazon.json` | 搜索 `Repro Notebook`，打开详情，加入一个商品；不结算 | 商品数据不变，购物车恰好包含 `P001`、数量 1 |

输入固定模型、种子数据、保留端口、任务、重置次数 3 与 verifier 次数 5。每次保存输入及渲染 prompt 的 SHA-256。固定输入不保证 LLM 输出一致；agent CLI 版本、服务端模型版本仍可能变化。需另外记录本机 `cursor-agent --version`；锁定其安装版本以跨机器复现。

## 运行

在**无个人凭据、无生产数据的临时容器或虚拟机**中执行生成代码。`cursor-agent --force` 及生成代码不是沙箱；本脚本的 loopback 浏览器限制不能替代操作系统隔离。只给该临时环境提供生成所需 `CURSOR_API_KEY`，不要提供 GitHub、Amazon、Slack 凭据。

Python 3.11/3.12；安装并认证官方 Cursor Agent CLI。上游要求 Node 18+，此功能最小实验要求生成 Python 标准库后端及 HTML/JS，无 npm 依赖。浏览器评估需固定 Playwright：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
export CURSOR_API_KEY='your-key'  # 推荐由临时环境秘密配置注入
python -m unittest discover -s tests -v

# 先生成、评估 GitHub；失败时先检查日志。每次生成必须使用全新目录。
python experiment.py generate --site github --run-dir runs/github-001
python experiment.py evaluate --site github --run-dir runs/github-001

# 再生成、评估 Amazon。
python experiment.py generate --site amazon --run-dir runs/amazon-001
python experiment.py evaluate --site amazon --run-dir runs/amazon-001
```

也可使用 `--site all`（默认）按 GitHub → Amazon 顺序运行两站。生成超时默认 900 秒，使用 `--timeout` 修改。退出码 0 代表本次所有选中站点通过，1 代表失败或阻塞。生成通过后才可进行评估，不能根据 agent 自述判断成功。

## 产物约定与测量

生成目录必须包含 `app.py`、`sdk.py`、`website_description.md`、`start_servers.sh`、`reset_servers.sh` 和 `task_instructions.json`。生成 prompt 明确规定 HTML test IDs、端点及 SDK 接口；测试契约是本实验的适配层，不是上游原生 API。

- `python app.py` 在前台监听固定 loopback 端口，`/health` 返回 `{"ok":true}`。
- `POST /reset` 恢复输入 seed；`GET /state` 只读持久状态。
- `sdk.Client(base_url).state()` 返回相同状态，`.reset()` 支持恢复。
- evaluator 启动自己的进程组并在结束时停止；占用端口时阻塞，不操作已有服务。
- 每轮先检查 reset 完全等于 seed，且 verifier 在初始状态为 false；执行真实浏览器搜索、详情及写操作。
- 写入后，用 SDK 读取状态 5 次，并与独立 HTTP 状态交叉核对。重复 3 次重置任务执行。
- `stable` 只表示布尔结果一致；持续 false 可以稳定但不成功。`all_passed` 与状态一致性必须同时通过。

## 日志与结果

`runs/<run>/<site>/` 保存冻结 `input.json`、`prompt.txt`、`manifest.json`、`generation.log`、`generation.json`、生成代码以及各评估目录。评估目录包含 `server.log`、`browser.log`（有消息时）、`failure.log`（失败时）、前后状态 JSON、最终截图和 Playwright trace ZIP。总体汇总为 `generation-summary.json` / `evaluation-summary.json`。同一生成可以重复评估，详细评估目录按时间独立保存；汇总指向最近一次评估结果。

生成 stdout/stderr 可能包含模型输出或秘密：运行目录默认不提交，分享日志前必须检查并删去凭据。故障日志保留原始失败；不将未运行步骤标记为通过。截图/trace 仅在浏览器成功初始化并进入相应阶段时产生。

## 本次实际结果与限制

2026-09-30 本环境 Python 3.12.14 / Node 24.19.0；没有 `cursor-agent` 和 Playwright，git clone 因网络代理不可达失败。通过 GitHub API 检查了真实上游脚本及固定 commit。`evidence/preflight/` 保存本次实际预检失败日志及冻结输入。

| 站点 | 生成 | 关键交互 | verifier 稳定性 |
|---|---|---|---|
| GitHub | blocked：缺少 cursor-agent | not_tested | not_tested |
| Amazon | blocked：缺少 cursor-agent | not_tested | not_tested |

已执行 3 项自动测试：判据负/正/重复写控制；稳定失败不误判成功；非零退出、超时与缺少执行器的日志记录。浏览器端到端流程未在此环境验证。它检验契约级功能与固定任务，不评估全站覆盖、真实站点兼容性、视觉相似度或 AgentLab 基准成绩。
