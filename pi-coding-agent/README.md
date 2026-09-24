# Pi worker

本目录保存 Pi Coding Agent 0.85.1 及其配置，供 Cairn Dispatcher 调用。
日常运行整个项目，请从项目根目录启动：

```bash
cd ~/blackboard-main
./start-cairn.sh
```

脚本自动读取根目录 `.env` 中的 `DEEPSEEK_API_KEY`，进入 Cairn 对话入口。
详细步骤见[项目 README](../README.md)和[完整运行指南](../docs/pi-text-local.md)。

## 配置与调用关系

- `pi`：启动脚本，定位本目录的依赖和配置。
- `package.json`、`package-lock.json`：Pi 依赖与锁文件。
- `node_modules/`：安装后的 Pi 程序。
- `agent/settings.json`：默认 provider 和模型设置。
- `agent/auth.json`：Pi 登录方式使用的凭证文件。

当前 Cairn 默认使用 `pi_dev` 通用开发适配器，以非交互方式调用本目录的 `pi`。
Pi 接收黑板上下文，调用模型和原生工具，返回结构化结果，由 Dispatcher 写回黑板。
模型配置当前指向 DeepSeek；线上可用性需要真实请求验证。

Cairn 保留 Pi 原生工具与资源发现机制，默认工具为 `read`、`write`、`edit`、`bash`。
不替换 Pi 默认系统提示词，追加通用开发 worker 的黑板输出协议。
项目扩展等资源沿用 Pi 原生的信任设置；后台 worker 没有交互式信任弹窗。
默认工作目录是 Cairn 项目根目录，也可以通过 `start-cairn.sh --workdir` 修改。
其 worker 会话和工具调用记录保存在 `~/.local/state/cairn/pi-dev-sessions/`。
可选的 `pi_text` 模式仍不启用工具，但已经不是默认启动模式。
直接运行本目录的 `./pi` 会进入 Pi 独立入口，不会自动启动 Cairn，
也不会自动读取父目录的 `.env`，因此不应把它当作整个项目的启动命令。

## 安装检查

在项目根目录执行：

```bash
./pi-coding-agent/pi --version
./pi-coding-agent/pi --help
```

Pi 0.85.1 要求 Node.js ≥ 22.19.0。缺少依赖时，在项目根目录执行：

```bash
npm ci --prefix pi-coding-agent --ignore-scripts
```

这些检查只验证本地程序，不会验证 DeepSeek key。
