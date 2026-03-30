SPEC.md: 本地多智能体异步协作网络 (Local Agent Mailbox Protocol)
1. 愿景与目标
构建一套极简、方便、高度可扩展的本地 AI Agent 协作中枢。系统采用“异步邮件投递”隐喻，解耦不同职能的智能体（如需求拆解、代码实现、Code Review）。
该网络致力于解决长周期、需要反复迭代的软件自动化开发流程，并兼容第三方独立 Agent（如 Claude Code、Cursor）的无缝接入，同时为未来的企业级或通用标准（如 ACP）预留演进空间。

2. 核心架构与概念
系统的核心分为三个主要实体：Agent（智能体节点）、Mail Broker（消息路由中枢） 和 Direct Skills（直连基础技能）。

2.1 实体定义
Mail Broker (中枢 Server)：以 HTTP Server 形式运行在本地，负责接收、存储、路由和分发“邮件”消息。

Agent (节点)：消息的发送方与接收方。每个 Agent 拥有独立的“邮箱地址”（如 planner@local, coder@local, reviewer@local）。

Thread (会话线程)：将多次往返的通信（如：打回重写的 Code Review）串联起来的上下文 ID。

2.2 两种通信模式 (双层网络)
异步协作网络 (通过 Broker)：Agent 之间通过读写邮件进行任务委派、结果反馈和代码审查。

同步技能调用 (Out-of-band 直连)：Agent 在执行具体任务时，绕过邮件系统，直接通过 HTTP 调用底层的原子化技能（如：操作浏览器、读写数据库、执行测试脚本）。

3. 核心元语与方法 (Mail Primitives)
Agent 与 Broker 之间的交互严格遵循以下核心元语：

Send (发送任务/消息)

功能：向指定的 Agent 地址投递结构化消息。

要素：收件人、发件人、主题、正文（Prompt/上下文）、附件（本地文件路径或代码片段）。

Read / Inbox (查收信件)

功能：Agent 获取属于自己地址的未读任务或反馈。

机制：支持轮询（Poll）拉取，或未来扩展为基于事件的推送。

Reply (回复/反馈)

功能：在同一个 Thread 下对收到的邮件进行回应。

场景：Code Reviewer 检查完毕后，使用 Reply 将修改建议发回给 Coder。

Forward (转发/流转)

功能：将当前任务及上下文完整打包，移交给下一个环节的 Agent。

场景：需求拆解 Agent 完成规格说明书后，Forward 给 Coder Agent 开始编码。

4. 身份与接入机制 (Identity & Integration)
系统设计了极其轻量的身份注册与鉴权机制，以兼容异构系统：

原生 Agent：通过代码启动时向 Broker 获取 Token，维持会话。

第三方 Agent (如 Claude Code)：采用“基于目录环境的静态身份注入”。

实现方式：在特定工作目录下放置配置文件（如 CLAUDE.md 或 .env），声明该目录对应的 Agent 身份（邮箱地址）和 Broker 访问凭证（Token）。

效果：当在目录 A 唤醒 Claude Code 时，它会自动读取指令，知道自己是 coder@local 并去查收 Coder 的 Inbox；在目录 B 唤醒时，它则化身为 reviewer@local。

5. 核心业务工作流示例 (软件开发生命周期)
启动 (User -> Planner)：人类（或系统）向 planner@local 发送一封邮件，包含原始的自然语言需求。

拆解 (Planner)：Planner 读取邮件，调用“浏览器直连技能”查阅资料，生成架构文档，随后 Forward 给 coder@local。

实现 (Coder)：位于特定工作目录的 Claude Code 读取 Inbox 获得任务，编写代码，调用“终端测试直连技能”运行。完成后 Reply 给 reviewer@local 申请合并。

审查 (Reviewer)：Reviewer 发现代码存在内存泄漏，通过 Reply 附带修改意见，将状态打回给 Coder。

闭环：Coder 修复后再次提交，Reviewer 通过，最终通知发起人。
