# Cairn + Pi 

本指南对应当前本地版本：Pi 位于 `blackboard-main/pi-coding-agent/`，作为 Cairn 的
`pi_dev` 通用开发 worker 使用。日常使用只需 `./start-cairn.sh` 一个启动脚本。
本文件沿用原来的文件名；旧的 `pi_text` 纯文本模式仍可显式选择。

## 1. 准备环境

如果把项目复制到新环境，需要：

- Linux 或 macOS。
- Python ≥ 3.12、uv。
- Node.js ≥ 22.19.0、npm。这是项目内 Pi 0.85.1 的 Node.js 要求。
- 可用的 DeepSeek API key，以及访问模型服务的网络。

在项目根目录安装 Python 依赖：

```bash
uv sync --locked --project cairn
```

如果 Pi 的 `node_modules` 尚未安装，在项目根目录执行：

```bash
npm ci --prefix pi-coding-agent --ignore-scripts
```

检查本地 Pi 和启动脚本：

```bash
./pi-coding-agent/pi --version
./start-cairn.sh --help
```

当前版本采用本机执行方式，不需要 Docker。
默认配置 `dispatch.pi-dev.yaml` 的 `local.working_directory` 为 `.`，统一启动时
按配置文件所在目录解释，因此默认在 Cairn 项目根目录工作。Pi 程序也按源码位置自动定位。
使用 `--workdir /绝对路径/你的项目` 可以选择其他工作目录。

## 2. 配置 API key

```bash
cd ~/blackboard-main
```

编辑根目录的 `.env`，在现有字段中填入 key：

```dotenv
DEEPSEEK_API_KEY=你的DeepSeek密钥
PI_TELEMETRY=0
```

已有 `.env` 时直接编辑，保留已有配置。仅在文件不存在时复制模板：

```bash
if [ ! -f .env ]; then cp .env.example .env; fi
```

`start-cairn.sh` 通过 `cairn-terminal` 调用 uv 加载根目录 `.env`，
凭证随后由 Dispatcher 传入 Pi 子进程，不需要另外 `source` 或 `export`。
修改 `.env` 后需要退出并重新启动。该文件已加入 Git 忽略规则。

Pi 使用 `pi-coding-agent/agent/settings.json` 中的模型设置。
当前本地配置为 provider `deepseek`、模型 `deepseek-v4-flash`；
线上是否可用，以实际 API 返回为准。启动脚本不会替你验证 key 或切换模型。

## 3. 一条命令启动整个架构

```bash
cd ~/blackboard-main
./start-cairn.sh
```

脚本会依次检查 Pi、启动本地黑板服务、启动 Dispatcher，并进入对话入口。
终端中会显示本次日志目录，然后出现：

```text
Cairn 已启动 · Pi worker · 通用开发模式 · 原生工具已启用
Pi 工作目录：/你的路径/blackboard-main
你>
```

直接输入完整需求并回车，例如：

```text
你> 请使用 shell 执行 pwd，然后读取 README.md，解释这个项目如何运行。
```

系统显示“Pi 正在处理…”；完成后以 `Pi>` 显示结果。
随后可以继续追问，下一轮会携带当前会话中已有的用户消息与 Pi 回复。
每次输入一行完整消息，本轮处理完成后再输入追问。

也可以从任意目录使用脚本的绝对路径启动。运行 `./cairn-terminal` 不带参数时，
同样会进入统一启动流程。

**无需另外启动 serve/dispatch，也无需手动执行 create/watch。**
网页和 API 文档页面已关闭；程序之间仍通过本机 HTTP API 通信。
即使在远程服务器上使用，也只需 SSH 终端，不需要网页端口转发。

## 4. 对话入口如何使用 Pi worker

```text
你在终端输入消息
       ↓
Cairn 对话入口将消息及上下文写入黑板
       ↓
Dispatcher 根据黑板状态派发任务
       ↓
项目内 Pi worker 调用 DeepSeek，按需调用原生工具，返回结构化结果
       ↓
Dispatcher 将结果写回黑板
       ↓
对话入口读取结果并显示 Pi 回复
```

每轮消息对应一个黑板项目，追问通过对话记录获得前文上下文。
这是 Cairn 的对话入口，Pi 仍由 Dispatcher 作为 worker 调用。
每轮还会附带本应用的架构说明，Pi 可以据此解释终端入口、黑板和 worker 的关系。
当 Pi 明确返回无法完成任务时，系统会把原因显示到终端并暂停本轮，不再重复提交相同输入。

默认配置保留 Pi 原生功能：`read`、`write`、`edit`、`bash` 默认启用；工具选择沿用
Pi 配置，不额外设置工具白名单。它可以读取文件、修改代码、运行 shell、构建和测试。
skills、扩展、提示词模板和项目上下文发现机制也保留。项目资源是否加载，遵循 Pi
原生的信任决策；非交互 worker 不显示信任弹窗，未信任的项目扩展可能不会加载。
需要交互界面的扩展功能不一定适用于后台 worker。

通用开发 worker 使用独立的 `development` 任务提示词，保留 Pi 默认系统提示词，
追加黑板输出协议和通用开发职责，不沿用自动攻击任务模板。
默认各轮任务在同一个项目根目录工作；shell 使用当前本机用户权限，没有额外的目录
或网络隔离。停止任务不会回滚已发生的修改。

这里是 Cairn 的逐轮对话入口，尚未嵌入 Pi 原生全屏 TUI，也不透传 Pi 的全部斜杠命令。
终端显示最终回复；原生工具调用与输出可以在 Pi 会话 JSONL 中查看。

看到 `你>` 只表示本地组件已启动。**首次发送消息时才会调用 DeepSeek，产生实际 API 请求。**
本地回归包含真实 Pi 程序与原生工具，通过本机模拟模型验证 shell、文件读写和黑板回写；
该测试不消耗 DeepSeek API，也不证明你的线上 key、网络或模型当前可用。

## 5. 停止、退出与新对话

| 操作 | 效果 |
| --- | --- |
| `/new` | 清空当前对话上下文，开始新对话；已保存的黑板记录保留 |
| `/status` | 查看当前项目的状态、事实和意图 |
| `/logs` | 打印本次服务日志目录 |
| `/help` | 显示可用命令 |
| `/quit` 或 `/exit` | 停止当前任务，关闭本次启动的调度器和服务 |
| 在输入提示处按 `Ctrl+C` | 退出整个会话并清理进程 |
| Pi 处理过程中按 `Ctrl+C` | 停止本轮，返回输入提示，可调整需求后继续 |

当前输入入口是逐轮对话。处理期间需要修改需求时，先按 `Ctrl+C` 停止本轮，再输入补充内容。
退出后重新启动，数据库和日志仍在，但对话入口会从新的上下文开始。
上次未完成的黑板项目会被暂停，不会因重启而自动继续调用模型。

## 6. 启动参数

| 参数 | 默认行为 | 用途 |
| --- | --- | --- |
| `--port` | 使用调度配置中的端口，当前为 8000 | 覆盖本机端口；0 表示自动选择空闲端口 |
| `--turn-timeout` | 300 秒 | 单轮对话总等待上限；超时停止本轮并返回输入提示 |
| `--data-dir` | 项目根目录下的 `datas/terminal` | 指定统一启动模式的数据库和日志目录 |
| `--config` | 项目根目录的 `dispatch.pi-dev.yaml` | 指定兼容配置；支持本地 `pi_dev` 或 `pi_text` workers |
| `--workdir` | 配置中的工作目录，默认项目根目录 | 指定通用开发 worker 的初始工作目录，各轮共享 |

常用示例：

```bash
./start-cairn.sh --port 0
./start-cairn.sh --turn-timeout 600
./start-cairn.sh --port 0 --data-dir ./datas/session-2
./start-cairn.sh --port 0 --workdir /绝对路径/你的项目
./start-cairn.sh --help
```

启动脚本会切换到项目根目录，相对 `--data-dir` 也按项目根目录解释。
`--turn-timeout` 是对话等待上限；单次 worker 的执行超时仍由 YAML 中的 `tasks` 配置控制。
同一数据目录同时只允许一个统一启动会话。
更新代码后请先在旧会话中 `/quit` 再重启，已运行的调度器不会自动加载新代码。

如需旧纯文本模式，可显式使用 `./start-cairn.sh --config dispatch.pi-text.yaml`。

## 7. 数据、日志和凭证位置

| 路径 | 内容 |
| --- | --- |
| `.env` | 本地 DeepSeek key |
| `dispatch.pi-dev.yaml` | 默认调度配置；一次运行一个通用开发 worker |
| `dispatch.pi-text.yaml` | 可选的旧纯文本配置 |
| `pi-coding-agent/agent/settings.json` | Pi 的默认 provider、模型 |
| `pi-coding-agent/agent/auth.json` | 使用 Pi 登录方式时的凭证；`.env` key 不会复制到此处 |
| `datas/terminal/cairn.db` | 统一启动使用的 SQLite 黑板数据库 |
| `datas/terminal/run-*/server.log` | 每次启动的黑板服务日志 |
| `datas/terminal/run-*/dispatcher.log` | 每次启动的任务执行日志 |
| `datas/terminal/session.lock` | 防止同一数据目录被重复启动的锁文件 |
| 项目根目录或 `--workdir` 指定目录 | 默认开发模式的实际工作目录，文件保留 |
| `~/.local/state/cairn/pi-dev-sessions/` | 开发 worker 的 Pi 会话及工具调用记录 |
| `~/.local/state/cairn/pi-text-sessions/` | 旧纯文本 worker 的会话记录 |

`--data-dir` 只改变统一启动的数据库和日志位置；工作目录由 `--workdir` 或 YAML 决定。
配置共享 `local.working_directory` 时须使用 `completed_action: keep`，不允许任务完成后删除代码目录。
手动执行 `cairn serve` 使用的默认数据库是 `~/.local/share/cairn/cairn.db`，
与统一脚本使用的数据库分开。

在对话中输入 `/logs` 获取准确目录。需要查看执行日志时，可在另一个终端运行：

```bash
# 将 run-实际目录名 替换为 /logs 显示的目录名
tail -n 80 datas/terminal/run-实际目录名/dispatcher.log
```

`/logs` 显示目录，不会直接打印日志内容。

## 8. 常见问题

### 提示端口被占用

如果之前手动启动过黑板服务，可在原终端按 `Ctrl+C` 关闭它，或者直接改用：

```bash
./start-cairn.sh --port 0
```

脚本会选空闲端口并同步给调度器，不会接管或结束占用端口的其他进程。

### 提示数据目录已有运行中的会话

先在原会话输入 `/quit`。如需第二个独立会话，使用另一个数据目录并自动分配端口：

```bash
./start-cairn.sh --port 0 --data-dir ./datas/session-2
```

锁文件存在本身不代表会话仍运行，文件锁会随进程退出而释放，不需要手动删除锁文件。

### 可以进入终端，但 Pi 一直没有回复

查看本次 `dispatcher.log`。本地启动检查不会验证 API key。
检查根目录 `.env` 是否填写正确，并在修改后重启脚本。
日志中的认证、额度、网络或模型错误需要分别处理；启动成功不代表这些条件已满足。

单轮默认等待 300 秒，超时后会停止任务并返回输入提示；也可以按 `Ctrl+C` 提前停止。

### 提示 Pi 启动检查失败

在项目根目录检查：

```bash
node --version
./pi-coding-agent/pi --version
```

确认 Node.js 满足版本要求、项目内 `node_modules` 已安装，且 Pi 启动脚本可执行。
缺少依赖时，使用第1节中的安装命令。

### 终端命令无法连接黑板

`project list/show` 等命令需要服务仍在运行。
默认连接 `127.0.0.1:8000`；如果修改端口，需传入实际地址：

```bash
./cairn-terminal project --server http://127.0.0.1:实际端口 list
```

通常直接使用对话内的 `/status` 即可，不需要另开管理终端。

## 9. 可选的终端管理与验证

服务运行期间，可以通过管理命令查看项目、导出记录。这不是日常对话的必要步骤：

```bash
./cairn-terminal project list
./cairn-terminal project show proj_001
./cairn-terminal project export proj_001 > result.yaml
./cairn-terminal project --help
```

`proj_001` 替换为实际项目 ID；管理命令与当前对话必须连接同一服务地址。
原有分开启动的 `serve` 和 `dispatch` 命令仍保留，供调试使用。

本地 worker 启动检查：

```bash
./cairn-terminal dispatch --config dispatch.pi-dev.yaml --startup-healthcheck-only
```

运行本地回归测试：

```bash
uv run --project cairn --group dev pytest -q
```
