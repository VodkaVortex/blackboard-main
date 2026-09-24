# Cairn + Pi：终端对话版

本项目使用 **Cairn 黑板协调任务，Pi 作为 worker，DeepSeek 提供模型推理**。
运行一个脚本即可进入终端对话，无需打开网页，也无需手动管理多个终端。

默认使用 `pi_dev` 通用开发 worker，保留 Pi 原生的 `read`、`write`、`edit`、`bash`
工具，以及 skills、扩展、项目上下文发现机制。Pi 可以读取源码、修改文件、执行命令和测试。
项目资源的加载沿用 Pi 自身的信任设置。

## 快速开始

### 1. 配置 DeepSeek API key

进入项目目录：

```bash
cd ~/blackboard-main
```

编辑项目根目录已有的 `.env`，填写下面这一项，保留其他配置：

```dotenv
DEEPSEEK_API_KEY=你的DeepSeek密钥
```

只有 `.env` 不存在时，才从模板创建：

```bash
if [ ! -f .env ]; then cp .env.example .env; fi
```

启动脚本自动加载 `.env`，不需要手动执行 `source` 或 `export`。
修改 key 后需要退出并重新启动脚本。

### 2. 整体启动

```bash
./start-cairn.sh
```

脚本会启动黑板服务、调度器和终端对话入口。看到 `你>` 后，直接输入需求，例如：

```text
你> 请使用 shell 执行 pwd，然后读取 README.md，用中文说明这个项目如何运行。
```

收到 `Pi>` 回复后可以继续追问。系统会自动将消息写入黑板、调度 Pi 并回传结果，
不需要执行 `project create` 或 `project watch`。

启动只检查本地程序能否运行，**首次发送消息才会调用 DeepSeek API**。
看到输入提示不代表 API key 或线上模型已经验证成功。

### 3. 退出

输入 `/quit`，脚本会停止当前任务并关闭本次启动的服务进程。
在输入提示处按 `Ctrl+C` 也会退出；Pi 正在处理时按 `Ctrl+C` 则只停止本轮，允许继续输入。

## 对话命令

| 命令 | 作用 |
| --- | --- |
| `/new` | 开始新对话，清空当前对话上下文 |
| `/status` | 查看本轮的黑板状态和记录 |
| `/logs` | 显示本次运行的日志目录 |
| `/help` | 查看对话命令 |
| `/quit` 或 `/exit` | 退出并关闭本次启动的进程 |

## 常用启动参数

```bash
# 默认端口被占用时，自动选择空闲端口
./start-cairn.sh --port 0

# 将单轮等待上限由默认300秒改为600秒
./start-cairn.sh --turn-timeout 600

# 使用独立的数据库和日志目录
./start-cairn.sh --port 0 --data-dir ./datas/session-2

# 在另一个代码目录中工作
./start-cairn.sh --port 0 --workdir /绝对路径/你的项目

# 查看完整参数
./start-cairn.sh --help
```

本地 HTTP 仅用于程序间通信，网页入口已关闭。当前启动方式不需要浏览器或 Docker。
默认工作目录是 Cairn 项目根目录，各轮任务共享该目录，文件修改会保留。
Shell 使用启动脚本的本机用户权限，没有额外的目录隔离；停止任务不会撤销已发生的修改。
入口仍是 Cairn 的逐轮对话终端，Pi 的原生全屏 TUI 和斜杠命令没有嵌入其中。

## 运行环境与数据

当前机器已安装依赖；如果在新环境部署，需要 Linux/macOS、Python ≥ 3.12、uv、
Node.js ≥ 22.19.0 和 npm。依赖安装步骤见[详细运行说明](docs/pi-text-local.md)。

| 位置 | 内容 |
| --- | --- |
| `dispatch.pi-dev.yaml` | 默认通用开发 Pi worker 和调度配置 |
| `dispatch.pi-text.yaml` | 可选的旧纯文本配置 |
| `pi-coding-agent/` | 项目内部的 Pi 本体及配置 |
| `datas/terminal/cairn.db` | 统一启动模式的黑板数据库 |
| `datas/terminal/run-*/` | 每次运行的服务端、调度器日志 |

重启后黑板记录仍保留，之前未完成的项目会暂停，不会自动重新执行。
终端对话上下文只在当前进程中保留，重启后从新对话开始。
修改 worker 配置或更新代码后，需要在旧终端 `/quit`，再重新运行脚本。

## 更多说明

- [完整运行指南与常见问题](docs/pi-text-local.md)
- [项目内 Pi worker 说明](pi-coding-agent/README.md)
- [许可证](LICENSE)
