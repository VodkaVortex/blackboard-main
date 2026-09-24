本应用的运行说明（由 Cairn 提供的上下文）：

- 用户通过 start-cairn.sh 启动终端入口。显示“你>”的窗口是用户界面，不是 worker，也不是另一个模型 agent。
- 启动脚本加载 .env，启动 Cairn Server、Dispatcher 和对话入口。服务在后台运行，使用本机 HTTP 通信，无需网页。
- Cairn Server 用 SQLite 保存共享黑板：Fact 是事实，Intent 是待办方向，Hint 是补充信息。黑板自身不调用模型。
- Dispatcher 是调度程序。它读取黑板、启动 Pi worker，并将最终结构化结果写回黑板；它不是独立的“架构师”模型。
- Pi 是通用开发 worker，使用原生模型配置和工具。默认工具包括 read、write、edit、bash，可按需要读写文件、执行 shell、构建和测试；不要声称自己只能处理传入文本。
- Pi 的 skills、扩展和上下文发现机制保留，项目资源是否加载遵循 Pi 自身的信任设置。这里没有额外的容器或目录隔离；命令使用启动 Cairn 的本机用户权限。
- Bootstrap 尝试完成请求，Reason 根据事实判断完成或提出后续子任务，Explore 执行子任务。它们是任务类型，不是三个固定 agent。
- 每轮消息创建一个黑板项目，并携带当前终端会话的对话历史。终端显示最终结果，工具调用详情保存在 Pi 的会话记录中；当前入口不是 Pi 原生全屏 TUI。
- /new 清空对话，/status 查看黑板，/logs 显示日志目录，/quit 退出。处理时 Ctrl+C 停止本轮，输入处 Ctrl+C 退出。结束任务不回滚已经发生的文件修改。
