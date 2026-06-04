# AgentWatch

**为 Claude Code 和 AI Agent 工作流打造的提醒工具，支持 Apple Watch / 安卓手机 + 手环/手表。**

AgentWatch 让你不用一直盯着 Claude Code。只有当 Agent 需要授权、需要你处理或任务完成时，它才通过 Bark 推送通知到你的手机，手腕上的 Apple Watch 或安卓手环（华为/小米/三星等，只需同步手机通知）随之震动并显示简短事件卡片。从此告别"离开 20 分钟回来发现 Agent 卡在权限弹窗等了 19 分钟"的尴尬。

> English users please see [README.md](README.md)

---

## 目录

1. [为什么需要 AgentWatch？](#为什么需要-agentwatch)
2. [核心卖点](#核心卖点)
3. [功能概览](#功能概览)
4. [工作原理](#工作原理)
5. [安装方式](#安装方式)
6. [macOS 快速开始](#macos-快速开始)
7. [Windows 快速开始](#windows-快速开始)
8. [Bark 配置](#bark-配置)
9. [Claude Code Hooks](#claude-code-hooks)
10. [通知策略](#通知策略)
11. [通知人格包](#通知人格包)
12. [macOS 菜单栏 App](#macos-菜单栏-app)
13. [Windows 托盘 App](#windows-托盘-app)
14. [常用命令](#常用命令)
15. [测试验证](#测试验证)
16. [常见问题排查](#常见问题排查)
17. [隐私与安全](#隐私与安全)
18. [路线图](#路线图)
19. [许可证](#许可证)
20. [参与贡献](#参与贡献)

---

## 为什么需要 AgentWatch？

Claude Code 很强大，但你不需要盯着它执行每一条命令。你只需要知道：

- 什么时候出现了"Allow this bash command?"真实权限弹窗
- Agent 需要你输入或确认什么
- 任务什么时候完成、等你验收
- 什么时候出了意外、需要你亲自处理

### 痛点场景

你让 Claude Code 处理一个任务，预计 10 分钟，于是起身去泡咖啡。回来发现 Claude Code 在权限确认弹窗等了 9 分钟——它一直在等你点击 Allow。

AgentWatch 就是为这个场景诞生的。它接入 Claude Code 的事件系统，过滤掉自动执行的噪音，只把**真正需要你介入**的事件推送到你手腕上。手表一震，看一眼卡片，立刻知道要不要冲回电脑前。

### 和其他方案对比

| | AgentWatch | 终端响铃 | Claude Code 官方推送 |
|---|---|---|---|
| 离开电脑也能收到 | ✅ | ❌（听不到） | ✅ |
| 免费 | ✅ | ✅ | ❌（需付费订阅） |
| 自动过滤噪音 | ✅ | ❌ | ❌ |
| 手表震动 + 事件卡片 | ✅ | ❌ | ❌ |
| 通知人格包 | ✅ | ❌ | ❌ |
| macOS / Windows 桌面客户端 | ✅ | ❌ | ❌ |
| 开源 | ✅ | N/A | N/A |

---

## 核心卖点

- 📱 **Apple Watch / 安卓手环震动 + 短卡片通知** — 标题、风险等级、建议动作一目了然。Bark 通知到达手机后，Apple Watch 或华为/小米/三星手环（同步手机通知）均会震动
- 🪝 **Claude Code 六 Hook 接入** — PreToolUse / PostToolUse / Notification / Stop / PermissionRequest / PermissionDenied
- 🔑 **PermissionRequest 支持** — 这才是捕获"Allow this bash command?"弹窗的**真正可靠来源**
- 🧠 **Actionable 通知模式** — 默认只在需要你动手时才推送，自动执行的工具不会吵你
- 🔇 **PreToolUse 超时默认 log-only** — 长时间编译/测试不会被误报为"需要权限"
- 🎭 **通知人格包** — 总裁版、少爷版、大小姐版、皇上版、甄嬛版，一键切换
- 🖥 **macOS 菜单栏 App** — 右上角常驻，原生 Swift + AppKit
- 🪟 **Windows 托盘 App** — 右下角常驻，原生 C# / .NET 8 WinForms
- 📋 **任务边界 + 静默跑偏记录** — Agent 跑偏时只记日志不震手表
- 📦 **零额外 Python 依赖** — 只用标准库
- 🔒 **本地优先** — 不调额外 LLM，不上传代码，不加遥测

---

## 功能概览

### 核心功能

| 功能 | 说明 |
|------|------|
| Apple Watch / iPhone 通知 | 通过 [Bark](https://apps.apple.com/app/bark/id1403753865)（免费开源）推送 |
| PermissionRequest Hook | 真正捕获"Allow this bash command?"弹窗 |
| PermissionDenied Hook | 记录你拒绝的操作 |
| Actionable 通知模式 | 只在需要你动手时才推送 |
| Stop Hook | 任务完成时提醒你 |
| PreToolUse 超时 log-only | 检测可能的权限等待，但不误报 |
| 通知人格包 | 六种通知风格，一键切换 |
| 任务边界 | 设置允许/禁止目录，跑偏静默记录 |
| 本地优先 | 不调用额外 LLM，不上传代码 |

### 桌面客户端

| 平台 | 客户端 | 技术栈 |
|------|--------|--------|
| macOS | 菜单栏 App（无 Dock 图标） | Swift + AppKit |
| Windows | 系统托盘 App | C# / .NET 8 WinForms |
| 跨平台 | CLI 命令行 | Python 3.10+，零额外依赖 |

### 通知人格包

| 主题 | Key | 风格 |
|------|-----|------|
| 关闭 | `off` | 标准 AgentWatch 文案 |
| 总裁版 | `boss` | 抓马爽剧风 |
| 少爷版 | `heir_male` | 管家汇报风 |
| 大小姐版 | `heir_female` | 管家汇报风 |
| 皇上版 | `emperor` | 太监请示风 |
| 甄嬛版 | `palace` | 后宫内务风 |

---

## 工作原理

```
Claude Code hooks           AgentWatch Python CLI
─────────────────         ─────────────────────────
PreToolUse         ──▶     危险/跑偏检测
PostToolUse        ──▶     失败计数
Notification      ──▶     注意分类
Stop              ──▶     任务完成
PermissionRequest ──▶     ✓ 推送手表（最可靠）
PermissionDenied  ──▶     仅记录（不推送）
                           │
                           ├── notification_policy（actionable 默认）
                           ├── persona 消息构建器
                           ├── Bark 推送 ──▶ iPhone ──▶ Apple Watch
                           └── logs/agentwatch_events.jsonl
```

**核心设计决策：**

- `PermissionRequest` 是**真"Allow"弹窗的最可靠信号**。它在 Claude Code 权限弹窗出现时精确触发。
- `Notification` 是通用"需要注意"的 fallback。
- `Stop` 处理任务完成。
- `PreToolUse` 超时**默认只记日志**——一个 4 秒的 PreToolUse-to-PostToolUse 间隔可能只是 Bash 命令跑得慢，不一定是权限弹窗。

---

## 安装方式

三种方式，从简到繁：

### 方式一：纯 CLI（最快）

不需要桌面客户端。核心功能（hooks → 手表通知）完全通过命令行工作。装 Python、clone 仓库、`pip install -e .`、配置 Bark、安装 hooks，几分钟搞定。见 [macOS 快速开始](#macos-快速开始)。

**这样就够了，通知已经在工作。**

### 方式二：下载预构建桌面客户端（推荐）

| 平台 | 下载 | 大小 |
|------|------|------|
| macOS (Apple Silicon) | [AgentWatch-macOS-arm64.zip](https://github.com/dongxutang918-afk/agentwatch/releases/download/v0.8.0/AgentWatch-macOS-arm64.zip) | 42 KB |
| Windows (x64) | [AgentWatch-Windows-x64.zip](https://github.com/dongxutang918-afk/agentwatch/releases/download/v0.8.0/AgentWatch-Windows-x64.zip) | 94 KB |

下载后解压运行：
- **macOS**：双击 `AgentWatch.app`（运行在菜单栏，无 Dock 图标）
- **Windows**：双击 `AgentWatchTray.exe`（运行在系统托盘，右下角）
- 然后从 App 菜单中配置 Bark key

> ⚠️ **一次性安装 Claude Code hooks**：打开终端，复制粘贴下面这行命令回车即可。安装后 App 和 hooks 各自独立运行——关掉 App 通知照样推送。
>
> **macOS：**
> ```bash
> bash ~/Projects/agentwatch/install_claude_hooks.sh
> ```
> **Windows：**
> ```powershell
> powershell -ExecutionPolicy Bypass -File %USERPROFILE%\Projects\agentwatch\windows\install_claude_hooks_windows.ps1
> ```

### 方式三：CLI + 从源码构建桌面客户端

Clone 仓库后，一条命令构建桌面 App（需要 Xcode Command Line Tools / .NET 8 SDK）。

---

## macOS 快速开始

### 前置条件
- macOS（Apple Silicon 或 Intel）
- Python 3.10+
- Claude Code（CLI 或 VS Code 插件）
- 手机安装 [Bark](https://apps.apple.com/app/bark/id1403753865)（免费，iOS / Android 均支持）
- Apple Watch（配对 iPhone）或安卓手环/手表（华为/小米/三星等，同步手机通知即可）

### 安装

```bash
# Clone 项目
git clone https://github.com/dongxutang918-afk/agentwatch.git ~/Projects/agentwatch
cd ~/Projects/agentwatch

# 设置 Python 环境
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 初始化（创建 config.json 和日志目录）
agentwatch init

# 配置 Bark key
agentwatch config bark        # 粘贴完整 Bark URL 或纯 key
agentwatch config test        # 验证通知链路是否打通

# 安装 Claude Code hooks（手动，一次性）
bash install_claude_hooks.sh

# 验证
agentwatch doctor             # 应显示 "Status: Ready"
```

### 可选：构建 macOS 菜单栏 App

```bash
bash macos/build_app.sh       # 需要 Xcode Command Line Tools（swift）
open build/AgentWatch.app     # 运行在菜单栏，无 Dock 图标
```

也可以直接双击这些文件（无需打开终端）：
- `AgentWatch Setup.command` — 首次安装
- `AgentWatch.command` — 日常启动
- `Open AgentWatch App.command` — 启动菜单栏 App

---

## Windows 快速开始

### 前置条件
- Windows 10 / 11
- Python 3.10+
- Claude Code（CLI 或 VS Code 插件）
- iPhone 安装 [Bark](https://apps.apple.com/app/bark/id1403753865)

### 安装

```powershell
# Clone 项目
cd %USERPROFILE%\Projects
git clone https://github.com/dongxutang918-afk/agentwatch.git
cd agentwatch

# 设置 Python 环境
powershell -ExecutionPolicy Bypass -File windows\setup_windows.ps1

# 配置 Bark key
.\.venv\Scripts\agentwatch.exe config bark
.\.venv\Scripts\agentwatch.exe config test

# 安装 Claude Code hooks（手动，一次性）
powershell -ExecutionPolicy Bypass -File windows\install_claude_hooks_windows.ps1

# 验证
.\.venv\Scripts\agentwatch.exe doctor
```

### 可选：构建 Windows 托盘 App

```powershell
# 需要 .NET 8 SDK（https://dotnet.microsoft.com）
powershell -ExecutionPolicy Bypass -File windows\build_app.ps1
build\windows\AgentWatchTray\AgentWatchTray.exe
```

也可以双击 `Open AgentWatch Windows App.bat`。

---

## Bark 配置

AgentWatch 通过 [Bark](https://apps.apple.com/app/bark/id1403753865)（免费开源推送 App，iOS / Android 均支持）发送通知。手机收到通知后，Apple Watch 或安卓手环会自动同步振动。

### 步骤

1. **在手机上安装 Bark**（iOS App Store 或 Android 应用商店）
2. **打开 Bark** → 首页显示的 URL 包含你的 key：
   ```
   https://api.day.app/YOUR_KEY/
                          ^^^^^^^^ 这就是你的 Bark key
   ```
3. **复制**完整 URL 或 key 部分
4. **粘贴**到 AgentWatch：

   | 方式 | 操作 |
   |------|------|
   | CLI | `agentwatch config bark` 然后粘贴 |
   | macOS 菜单栏 | `● AW` → `Add / Update Bark Key...` → 粘贴 |
   | Windows 托盘 | 右键 → `Add / Update Bark Key...` → 粘贴 |

5. **测试**：`agentwatch config test`（或在 GUI 中点击 Test Push）

你应该在手机和手表/手环上收到"AgentWatch Bark 测试"通知。

### 确认手机 / 穿戴设备同步
- iPhone：设置 → 通知 → Bark → 允许通知 ✅
- Android：设置 → 通知 → Bark → 允许通知 ✅
- Apple Watch：Watch App → 通知 → 从 iPhone 镜像 Bark ✅
- 安卓手环/手表（华为/小米/三星等）：在手机端配套 App（如华为运动健康）中开启 Bark 的通知同步即可

---

## Claude Code Hooks

Hooks 是**手动、选择性**的——AgentWatch 不会自动修改你的 Claude Code 配置。安装前会备份 settings.json。

六个 Hooks 被注册：

| Hook | 触发时机 | AgentWatch 行为 |
|------|---------|----------------|
| `PreToolUse` | Agent 即将调用工具 | 危险/跑偏检测 + 注册 pending action |
| `PostToolUse` | Agent 完成工具调用 | 清除 pending action，追踪失败 |
| `Notification` | Agent 发送通知 | 分类为 attention_required（fallback） |
| `Stop` | Claude Code 会话结束 | 推送"任务完成"到手表 |
| `PermissionRequest` | **"Allow this bash command?"弹窗出现** | 推送"需要权限"到手表 |
| `PermissionDenied` | 用户点击"No"拒绝权限 | 仅记录日志 |

**macOS：**
```bash
bash install_claude_hooks.sh     # 安装
bash uninstall_claude_hooks.sh   # 卸载
```

**Windows：**
```powershell
powershell -ExecutionPolicy Bypass -File windows\install_claude_hooks_windows.ps1
powershell -ExecutionPolicy Bypass -File windows\uninstall_claude_hooks_windows.ps1
```

> ⚠️ **升级提醒：** 如果你在 v0.8.0 之前安装了 hooks，需要重新运行安装脚本以添加 `PermissionRequest` 和 `PermissionDenied`。运行 `agentwatch doctor` 应显示 `Claude hooks: Installed`（6/6）。

---

## 通知策略

AgentWatch 默认使用 **actionable 模式**——只有真正需要你介入的事件才推送手表。

### ✅ 推送到手表

| 事件 | 来源 Hook | 示例 |
|------|----------|------|
| 真实的"Allow this command?"弹窗 | PermissionRequest | "Claude 需要你批准运行：rm -rf build/" |
| Agent 需要你注意 | Notification（fallback） | "Claude 在等待你输入" |
| 任务完成 | Stop | "任务完成，请验收" |

### ❌ 仅记录日志（不震手表）

| 事件 | 来源 | 原因 |
|------|------|------|
| 你拒绝了某个权限 | PermissionDenied | 无需操作 |
| 工具调用尚未返回 | PreToolUse timeout | 可能是缓慢命令，不一定是权限弹窗 |
| 高风险操作 | PreToolUse 危险关键词 | actionable 模式下静默 |
| 任务边界跑偏 | PreToolUse 禁止路径 | 静默记录 |
| 连续失败 | PostToolUse 错误计数 | 静默记录 |

### 切换模式

推送所有事件（verbose 模式）：
```json
"notification_policy": { "mode": "verbose" }
```

允许 PreToolUse timeout 也推送（接受长命令误报风险）：
```json
"approval_detection": { "timeout_watch_notify": true }
```

---

## 通知人格包

从 GUI 或 CLI 切换通知风格，无需重启。六种主题可选：

| 主题 | Key | 通知示例 |
|------|-----|---------|
| 关闭 | `off` | "需要权限 / Agent 正在等待你允许操作" |
| 总裁版 | `boss` | "总裁快签字 / 总裁！没有您的签字，整个项目组..." |
| 少爷版 | `heir_male` | "待您过目 / 少爷，这一步管家不敢擅自处理..." |
| 大小姐版 | `heir_female` | "待您过目 / 大小姐，这一步管家不敢擅自处理..." |
| 皇上版 | `emperor` | "奏请御批 / 皇上，奴才这儿有道折子..." |
| 甄嬛版 | `palace` | "请主子示下 / 主子，这一步内务府不敢擅自做主..." |

**CLI：**
```bash
agentwatch persona show               # 显示当前主题
agentwatch persona set boss           # 切换总裁版
agentwatch persona set emperor        # 切换皇上版
agentwatch persona off                # 关闭人格包
agentwatch persona test permission    # 预览文案（不推送）
agentwatch persona test done          # 预览文案（不推送）
```

**macOS：** `● AW` → `Persona Theme` → 选择主题

**Windows：** 右键托盘图标 → `Persona Theme` → 选择主题

人格包只改变通知**文案**，不改变通知**策略**（哪些事件推送）。

---

## macOS 菜单栏 App

原生 Swift + AppKit 应用，运行在菜单栏（无 Dock 图标），右上角可见 `● AW`。

### 构建与启动

```bash
bash macos/build_app.sh          # 构建（需要 Xcode CLT：swift）
open build/AgentWatch.app        # 启动
# 或双击：Open AgentWatch App.command
```

### 功能

| 操作 | 说明 |
|------|------|
| Bark 配置 | 添加/更新 Bark key、查看当前配置（key 脱敏） |
| Test Push | 发送测试通知验证链路 |
| Persona Theme | 六种主题切换，当前选中带勾选 |
| Recent Events | 最近 5 条非 info 事件，带图标、时间和 notified/logged 标签 |
| Hook 状态 | 显示 6 hooks 是否安装完整；缺少 PermissionRequest 时提示 |
| Approval Timeout Notify | 显示 PreToolUse timeout 推送是否开启 |
| 任务边界 | 管理允许/禁止路径 |
| 快捷入口 | 打开 Logs 文件夹、config.json、README |
| Monitor | 在终端中启动 ANSI 监控面板 |

---

## Windows 托盘 App

原生 C# / .NET 8 WinForms 应用，运行在系统托盘（右下角）。

### 构建与启动

```powershell
# 需要 .NET 8 SDK
powershell -ExecutionPolicy Bypass -File windows\build_app.ps1
build\windows\AgentWatchTray\AgentWatchTray.exe
# 或双击：Open AgentWatch Windows App.bat
```

### 功能

与 macOS 菜单栏 App 保持一致，额外增加：
- **Preview Current Persona** — 预览当前主题通知文案，不发送推送
- **Test Permission Request / Denied** — 模拟特定 Hook 事件

---

## 常用命令

| 命令 | 说明 |
|------|------|
| `agentwatch doctor` | 全面健康检查 |
| `agentwatch monitor` | 实时 ANSI 监控面板（Ctrl+C 退出） |
| `agentwatch start` | doctor 检查 → monitor 面板 |
| `agentwatch init` | 创建 config.json 和日志目录 |
| `agentwatch config bark` | 设置 Bark key（支持完整 URL 或纯 key） |
| `agentwatch config show` | 显示 Bark 配置（key 脱敏） |
| `agentwatch config test` | 发送测试通知 |
| `agentwatch persona show` | 显示当前人格包主题 |
| `agentwatch persona set <主题>` | 切换人格包 |
| `agentwatch persona off` | 关闭人格包 |
| `agentwatch persona test <事件>` | 预览人格包文案（不推送） |
| `agentwatch simulate permission-request` | 模拟权限弹窗 → 应推送 |
| `agentwatch simulate permission-denied` | 模拟拒绝权限 → 应仅记录 |
| `agentwatch simulate done` | 模拟任务完成 → 应推送 |
| `agentwatch simulate approval-pending` | 模拟超时 → 应仅记录 |
| `agentwatch task quick` | 交互式设置任务边界 |
| `agentwatch task clear` | 清除任务边界 |
| `agentwatch logs --tail 20` | 查看最近 20 条事件日志 |

---

## 测试验证

安装完成后，运行以下命令验证：

```bash
# 1. 健康检查
agentwatch doctor
# 预期：Status: Ready，Claude hooks: Installed

# 2. 测试通知链路
agentwatch config test
# 预期：iPhone / Apple Watch 收到通知

# 3. 模拟真实权限弹窗
agentwatch simulate permission-request
# 预期：手表收到当前人格包风格的通知

# 4. 模拟任务完成
agentwatch simulate done
# 预期：手表收到"任务完成"通知

# 5. 这些不应该推送（默认 log-only）：
agentwatch simulate approval-pending    # 超时 → 仅记录
agentwatch simulate permission-denied   # 拒绝 → 仅记录
```

---

## 常见问题排查

### 手机 / 手表没有震动
1. 确认手机上 Bark 安装并正常工作（在 Bark App 内发一条测试消息）
2. 运行 `agentwatch config test` — 应显示"Notification sent"
3. iPhone：设置 → 通知 → Bark → 允许通知 ✅
4. Android：设置 → 通知 → Bark → 允许通知 ✅
5. Apple Watch：Watch App → 通知 → 从 iPhone 镜像 Bark ✅
6. 安卓手环/手表：在华为运动健康 / 小米穿戴 / Galaxy Wearable 等配套 App 中开启 Bark 通知同步

### Bark 返回 "device token not found"
- Bark key 可能填错或过期
- 打开 iPhone Bark App → 复制当前 URL
- 确认 config.json 中 `bark_server` 为 `https://api.day.app`

### 电脑端出现 "Allow this bash command?"，但手表没提醒
1. 运行 `agentwatch doctor` — 是否显示 `Missing PermissionRequest`？
2. 如果是，重新安装 hooks：
   - macOS：`bash install_claude_hooks.sh`
   - Windows：`powershell -File windows\install_claude_hooks_windows.ps1`
3. 测试：`agentwatch simulate permission-request`
4. **重启 Claude Code 会话**——新 hooks 只在新 session 生效

### 长 Bash 命令频繁误报"需要权限"
- 这是**默认行为**——PreToolUse 超时只记日志 (`timeout_watch_notify: false`)
- 确认 config 中 `approval_detection.timeout_watch_notify` 为 `false`
- 长编译、测试等操作不会触发手表通知

### macOS App 双击没窗口
- 它是**菜单栏 App**——看屏幕右上角 `● AW` 图标
- 没有 Dock 图标，没有窗口，点击图标弹出菜单

### Windows 托盘 App 没启动
- 确认 .NET 8 SDK 已安装：`dotnet --version`
- 重新构建：`powershell -File windows\build_app.ps1`
- 检查 `build\windows\AgentWatchTray\AgentWatchTray.exe` 是否存在

### Hooks 已安装但 doctor 显示 Missing
- 检查 `~/.claude/settings.json` 中 Python 路径是否指向正确的 `.venv`
- 如果移动过项目目录，需要重新运行安装脚本

---

## 隐私与安全

| 项目 | 状态 |
|------|------|
| Bark key 被上传到 Git | ❌ 已阻止（config.json 被 gitignore） |
| 日志被上传到 Git | ❌ 已阻止（logs/ 和 diagnostics/ 被 gitignore） |
| 源代码被发送到外部 LLM | ❌ 否——AgentWatch 不调用任何 AI API |
| 通知内容传输到 Bark 服务器 | ✅ 仅标题+正文。支持自建 Bark server |
| 日志中包含 Bark key | ❌ 写入前自动脱敏 |
| Claude Code 配置被修改 | ✅ 只有你手动运行安装脚本时 |

详见 [SECURITY.md](SECURITY.md)。

---

## 路线图

- [ ] GitHub Release 二进制文件（预构建 `.app` 和 `.exe`）
- [ ] Away mode — 自动检测你离开电脑时启用高强度监控
- [ ] 会话摘要通知 — 总结 Agent 完成了什么
- [ ] Guard mode — 危险操作自动阻断
- [ ] 更多通知人格包
- [ ] Pushover / ntfy 推送后端支持
- [ ] 原生 iOS / watchOS 操作（手腕批准/拒绝）

---

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

## 参与贡献

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。
