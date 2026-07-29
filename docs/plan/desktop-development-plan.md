# Anime Accurate Sub Electron 桌面版开发计划

> 总需求：[Issue #190](https://github.com/caiyilian/Anime-Accurate-Sub/issues/190)
> 制定日期：2026-07-29
> 目标平台：Windows 10/11 x64，首版同时保留跨平台架构边界

## 1. 交付目标

在仓库根目录新增独立的 `desktop/` Electron 应用。用户不再需要手写 PowerShell 命令，
即可完成：

1. 拖拽或选择一个/多个 MP4；
2. 配置翻译、ASR、上下文、术语/记忆和三类质量开关；
3. 顺序启动 `scripts/anime_sub.py`，实时查看命令、阶段、百分比和 stdout/stderr；
4. 取消当前任务，并在同一输出目录重新启动以利用现有 checkpoint 续跑；
5. 完成后播放硬字幕 MP4、查看 SRT/ASS、打开目录并导出日志；
6. 使用 NSIS 安装器安装、启动和卸载桌面版。

桌面版是现有 Python CLI 的安全图形外壳，不复制翻译、ASR、MQM 或字幕业务逻辑。CLI 仍是
唯一业务真源，桌面端只负责参数建模、进程生命周期、状态解释和结果交互。

## 2. 调研依据与技术决策

### 2.1 OpenCode Desktop 可复用模式

已完整阅读本机：

- `E:\projects\opencode\packages\desktop\ARCHITECTURE.md`
- `src/main/index.ts`、`windows.ts`、`server.ts`、`ipc.ts`、`store.ts`、`logging.ts`
- `src/preload/index.ts` / `types.ts`
- `electron.vite.config.ts`、`electron-builder.config.ts`、`package.json`

直接沿用的架构模式：

| OpenCode 模式 | 本项目适配 |
|---|---|
| Main / Preload / Renderer 三进程职责 | 完整采用 |
| `contextIsolation=true`、`nodeIntegration=false`、`sandbox=true` | 完整采用 |
| Preload 只暴露窄而有类型的 API | 完整采用，命名为 `window.desktopAPI` |
| 主进程统一注册 IPC handler | 完整采用，渲染进程不接触 Node API |
| electron-store 仅由主进程持有 | 完整采用 |
| electron-log 分 scope 记录运行日志 | 完整采用 |
| 单实例锁、窗口状态恢复、加载失败处理 | 采用简化版本 |
| Sidecar 启动/就绪/停止/强杀生命周期 | 适配为 Python CLI 队列进程 |
| 安全自定义协议访问本地资源 | 适配为只读结果媒体协议 |
| electron-vite 三入口构建 | 完整采用 |
| electron-builder + NSIS | 完整采用 |

不直接复制的部分：

- OpenCode Sidecar 是常驻 HTTP 服务；本项目是每个视频一个长生命周期 CLI 子进程，因此使用
  `child_process.spawn` 和事件流，不增加无必要的 HTTP 层。
- 不需要 OpenCode 的多窗口、深链接、WSL、自动更新、Sentry、PTY 或复杂 Effect 启动图。
- OpenCode UI 属于独立包且受其设计系统约束；本项目只参考信息层级和交互密度，不复制品牌
  组件或业务界面。

### 2.2 固定技术栈

下表版本在 2026-07-29 使用 npm registry 的 stable tag 核对：

| 层面 | 选择 | 初始版本 |
|---|---|---:|
| 桌面容器 | Electron | 43.2.0 |
| 构建 | electron-vite | 5.0.0 |
| 打包 | electron-builder | 26.15.3 |
| UI | React | 19.2.8 |
| 样式 | Tailwind CSS | 4.3.3 |
| 配置存储 | electron-store | 11.0.2 |
| 日志 | electron-log | 5.4.4 |
| 单元测试 | Vitest + Testing Library | 与 Vite 兼容的稳定版 |
| UI/桌面烟测 | Playwright Electron 或内建 smoke 模式 | 稳定版 |

选择 React 而不是 SolidJS，是因为本项目没有 OpenCode 的 SolidJS 共享 UI 包，React 的表单、
测试和桌面生态更成熟，符合 Issue #190“不追求轻量、优先成熟生态”的原则。

### 2.3 多视频策略

首版支持选择多个 MP4，但采用顺序队列：

- 同一时刻只运行一个 Python Pipeline，避免 ASR GPU、Ollama 和 SenseNova 并发争用；
- 队列中每个视频拥有独立状态、日志、输出目录和结果；
- 可取消当前项，未开始项保持 pending；
- 再次启动相同视频和输出根目录时，由 Python 的 `checkpoint.json` 与 JSONL 进度自动续跑。

### 2.4 Python 与项目根目录检测

主进程依次检测：

1. 用户持久化的 Python 路径；
2. `<project>/.venv/Scripts/python.exe`；
3. `D:\miniconda3\python.exe`（本机兼容项）；
4. `python` / `python3`（PATH）。

项目根目录依次来自：

1. 用户持久化设置；
2. `ANIME_ACCURATE_SUB_ROOT`；
3. 开发模式中 `desktop/` 的父目录；
4. 安装包的 `resources/backend`。

启动前运行只读诊断：Python `--version`、`scripts/anime_sub.py` 是否存在、必要配置路径是否
存在。失败时阻止启动并显示可操作的中文提示，不把错误延迟到长流程中途。

### 2.5 安全边界

- Renderer 无 Node.js 权限，不能任意读写文件或启动进程；
- 所有 IPC payload 在主进程重新校验，不能信任 TypeScript 类型本身；
- 只接受存在的 MP4/MKV/AVI/MOV/WEBM 视频路径；
- 配置文件、术语表、系列记忆、日文字幕按扩展名和存在性校验；
- 启动 Python 使用 `spawn(executable, args, {shell:false})`，绝不拼接 shell 命令；
- 结果访问必须位于当前任务工作目录内，防止 `../` 路径逃逸；
- 自定义媒体协议仅允许已登记任务的结果文件；
- 日志导出通过原生保存对话框，不接收 Renderer 任意目标路径；
- 打包配置明确排除 `.githubtoken.txt`、`sensenova_apikeys` 和所有本机密钥。

## 3. 目标目录结构

```text
desktop/
├── src/
│   ├── main/
│   │   ├── index.ts              # 生命周期、单实例、协议与服务装配
│   │   ├── windows.ts            # BrowserWindow 与窗口状态
│   │   ├── ipc.ts                # IPC handler 注册和输入校验
│   │   ├── store.ts              # electron-store 配置封装
│   │   ├── logging.ts            # electron-log 与导出
│   │   ├── environment.ts        # Python/项目根目录诊断
│   │   ├── command.ts            # Pipeline 参数到 argv 的纯函数
│   │   ├── pipeline.ts           # 子进程队列、取消、续跑
│   │   ├── checkpoint.ts         # checkpoint/MQM/结果解析
│   │   └── results.ts            # 结果发现和安全媒体协议
│   ├── preload/
│   │   ├── index.ts              # contextBridge
│   │   └── types.ts              # IPC DTO 与 DesktopAPI
│   └── renderer/
│       ├── index.html
│       ├── index.tsx
│       ├── App.tsx
│       ├── components/
│       │   ├── TitleBar.tsx
│       │   ├── DropZone.tsx
│       │   ├── QueuePanel.tsx
│       │   ├── ConfigPanel.tsx
│       │   ├── ProgressPanel.tsx
│       │   ├── LogPanel.tsx
│       │   └── ResultPanel.tsx
│       ├── hooks/
│       └── styles.css
├── tests/
│   ├── unit/
│   ├── renderer/
│   ├── integration/
│   └── smoke/
├── resources/
│   ├── icon.ico
│   └── icon.png
├── scripts/
├── electron.vite.config.ts
├── electron-builder.config.ts
├── package.json
├── tsconfig.json
└── vitest.config.ts
```

## 4. IPC 契约草案

| API | 类型 | 作用 |
|---|---|---|
| `pickVideos()` | invoke | 多选视频 |
| `pickFile(kind)` | invoke | 日文字幕/术语/记忆/配置 |
| `pickDirectory()` | invoke | 输出根目录/项目根目录 |
| `getSettings()` / `saveSettings()` | invoke | 持久化用户配置 |
| `diagnoseEnvironment()` | invoke | Python、CLI、FFmpeg、模型就绪状态 |
| `previewCommand(request)` | invoke | 返回 executable + args 的可审计预览 |
| `startQueue(request)` | invoke | 启动顺序队列 |
| `cancelCurrent()` | invoke | 终止当前子进程树 |
| `getQueueSnapshot()` | invoke | 获取当前完整快照 |
| `onQueueEvent(listener)` | event | 状态、进度、日志和结果增量 |
| `listResults(jobId)` | invoke | 返回已验证结果元数据 |
| `readSubtitle(jobId, kind)` | invoke | 读取有限大小的 SRT/ASS 文本 |
| `openOutputDirectory(jobId)` | invoke | 使用系统文件管理器打开目录 |
| `exportLog(jobId)` | invoke | 通过保存对话框导出日志 |
| `resultMediaUrl(jobId)` | invoke | 生成安全只读媒体 URL |
| `windowMinimize/Maximize/Close()` | send | 自定义标题栏 |

事件统一为带 `jobId`、`sequence`、`timestamp` 的判别联合类型，Renderer 可以幂等合并，避免
日志和 checkpoint 轮询事件乱序。

## 5. Pipeline 命令模型

`command.ts` 以纯函数把结构化设置映射为 argv，至少覆盖：

- 视频路径与 `--output-dir`；
- `--backend`、`--asr-backend`；
- `--config`、`--review-config`、`--mqm-config`；
- `--multi-agent-review`、`--mqm-quality-review`、`--quality-check`；
- `--translation-context-window`、`--translation-memory`；
- `--memory`、`--glossary`；
- `--prefer-japanese-subtitles` / `--japanese-subtitle`；
- `--oped-series`、`--episode-number`、`--oped-best-effort`。

UI 展示“当前正在执行的命令”时使用专门的安全显示转义；实际执行始终传递 argv 数组，显示
字符串绝不反向参与执行。

## 6. 进度模型

### 6.1 阶段来源

优先读取每集工作目录 `checkpoint.json`。阶段顺序按实际启用项动态构造：

```text
japanese_subtitle 或 extract_audio + asr
→ translate
→ multi_agent_review（可选）
→ mqm_quality_review（可选）
→ subtitle
→ embed_subtitle
→ quality_check（可选）
```

### 6.2 阶段内进度

- 解析日志中的 `Translated: x/y`、`Reviewed: x/y` 和 MQM `x/y`；
- 没有计数信息时使用阶段级进度，不伪造精确百分比；
- 总体百分比由“已完成阶段 + 当前阶段内部比例”计算；
- checkpoint 文件读取失败时保留上次成功快照并发出 warning，不把瞬时原子替换视为任务失败。

### 6.3 终态

`pending → running → cancelling → cancelled/completed/failed`。进程 exit code 0 仍要验证预期输出；
取消后保留工作目录和 checkpoint，重新排队同一任务即为续跑。

## 7. 分阶段实施与强制流程

每个 D1-D7 阶段都必须严格执行：

1. 创建独立中文 Issue 并回读验证正文；
2. 在当时最新 `master` 上实现和测试；
3. 创建 `codex/desktop-dN-*` 临时分支并只提交本阶段文件；
4. 创建合并到 `master` 的 PR；
5. 在 Issue 中追加中文完成评论，包含解决内容、实现方式、完整提交 SHA、PR 链接；
6. 回读验证评论无乱码、SHA/PR 完整；
7. 合并 PR、关闭 Issue；
8. 删除本地和远程临时分支；
9. 切回并拉取最新 `master`；
10. 才能创建下一阶段 Issue。

### D1：脚手架、构建链和空窗口

范围：

- 初始化 `desktop/package.json`、lockfile、TypeScript、electron-vite、React、Tailwind；
- 创建 Main/Preload/Renderer 最小入口；
- 创建安全 BrowserWindow、单实例锁和开发/生产加载路径；
- 配置 electron-builder NSIS 基础项和占位资源；
- 增加 lint/typecheck/unit/build 脚本。

验收：

- `npm ci` 可复现安装；
- typecheck、unit、electron-vite build 全部通过；
- Electron smoke 模式成功创建窗口并完成 Renderer 首屏加载；
- 空窗口不开放 Node 集成。

### D2：Main/Preload、安全 IPC、存储和环境诊断

范围：

- 实现窗口状态、原生文件/目录选择器、最小化/最大化/关闭；
- electron-store 配置 schema 与迁移；
- electron-log 主进程日志；
- Python/项目根目录/CLI/FFmpeg/模型只读诊断；
- 类型安全 `desktopAPI` 和主进程 payload 校验。

验收：

- Renderer 只能通过 Preload 白名单调用；
- 文件选择、配置保存/重启恢复、环境诊断有单元和 IPC 集成测试；
- 非法路径、非法枚举和越界 payload 被拒绝；
- 本机能检测到 `D:\miniconda3\python.exe` 和项目 CLI。

### D3：多视频选择与 Pipeline 配置界面

范围：

- 完整桌面布局、拖拽区、队列、配置表单、阶段/日志/结果占位面板；
- 单个/多个 MP4 点击选择与拖拽校验、去重、删除、重排；
- 基础/高级两级配置，覆盖 Issue #190 列出的所有关键 CLI 参数；
- 环境诊断状态和命令预览；
- 响应式、键盘可用性和中文错误提示。

验收：

- Renderer 组件测试覆盖拖拽、多选、校验、表单和命令预览；
- 1280×800 与较小窗口布局可用；
- 不出现横向溢出、控制台错误或无标签表单控件。

### D4：Python Pipeline 顺序队列与生命周期

范围：

- argv 纯函数和完整参数映射；
- `spawn(shell:false)`、stdout/stderr 增量解码、日志落盘；
- 多视频顺序队列、当前任务取消、应用退出清理；
- Windows 子进程树终止和超时强杀；
- 相同输出目录续跑语义。

验收：

- 单元测试逐项断言 argv，无 shell 注入路径；
- 使用可控 Python fixture 验证成功、失败、取消、队列推进和日志；
- 真实 `scripts/anime_sub.py --version` 经桌面进程管理器启动成功；
- 取消不删除 checkpoint 或已有结果。

### D5：checkpoint 解析、总体进度和实时日志

范围：

- 安全读取/解析 `checkpoint.json` 和日志计数；
- 文件轮询、瞬时读取错误容错、阶段映射和百分比；
- IPC 增量事件序号与 Renderer 幂等合并；
- 进度面板、阶段时间线、自动滚动/暂停日志和日志级别。

验收：

- fixture 覆盖日文字幕分支与 ASR 分支、可选审查开关；
- 进度单调、不超过 100%，终态与进程/产物一致；
- 模拟 Pipeline 时 UI 实时显示阶段、进度、命令和日志；
- 高频日志不会令 Renderer 明显卡顿。

### D6：结果发现、字幕查看、视频播放与日志导出

范围：

- 验证并列出 SRT、ASS、`*_subs.mp4`、质量报告；
- 注册只读安全媒体协议，浏览器原生 `<video>` 播放；
- 有大小上限的字幕查看器；
- 打开输出目录、定位文件、导出任务日志；
- 完成态结果卡和缺失产物解释。

验收：

- 路径遍历和非任务文件访问被拒绝；
- 使用现有《轻音少女》最终产物实际播放 MP4 元数据并读取 SRT/ASS；
- 打开目录和日志导出 IPC 测试通过；
- 结果缺失不会导致应用崩溃。

### D7：NSIS、真实短片流程和最终验收

范围：

- 正式图标、产品元数据、NSIS 安装/卸载配置；
- 仅打包安全后端资源，显式排除密钥和大模型；
- 开发版与安装版 smoke；
- 用《轻音少女》60 秒片段通过桌面管理路径完成真实 Pipeline；
- 完成用户文档、架构文档和 Issue #190 验收清单。

验收：

- `npm ci`、lint、typecheck、unit、renderer、integration、build 全通过；
- NSIS `.exe` 生成成功，可静默安装、启动 smoke、静默卸载；
- 安装目录不包含 GitHub/SenseNova 密钥；
- 真实短片产出 SRT、ASS、硬字幕 MP4 和质量报告；
- 取消后重新启动能从 checkpoint 继续；
- Issue #190 全部九项验收标准有可追溯证据。

## 8. 测试矩阵

| 层级 | 工具/方式 | 重点 |
|---|---|---|
| 纯函数 | Vitest | argv、校验、checkpoint、结果路径 |
| Main IPC | Vitest + Electron mock/真实 invoke harness | 安全桥、store、dialog、shell |
| Renderer | Testing Library + jsdom | 拖拽、表单、队列、进度、结果 |
| 子进程集成 | Python fixture | 日志、进度、取消、退出码、队列 |
| Electron smoke | 内建 `--smoke-test`/Playwright | BrowserWindow 与首屏加载 |
| 真实短片 | 60 秒《轻音少女》 | CLI 全链路和结果交互 |
| 打包 | electron-builder NSIS | 安装、启动、卸载、密钥扫描 |
| Python 回归 | `pytest` + `scripts/test_all.py` | 不破坏现有 S0-S16 |

## 9. 最终验收映射

| Issue #190 验收项 | 负责阶段 |
|---|---|
| 桌面版正常启动并显示主窗口 | D1、D7 |
| 拖拽/点击选择 MP4 | D3 |
| 配置 Pipeline 参数 | D2、D3 |
| 点击开始后 Python Pipeline 执行 | D4、D7 |
| 实时阶段、进度和日志 | D5 |
| 查看字幕和播放视频 | D6 |
| 中断后断点续传 | D4、D5、D7 |
| NSIS 安装和卸载 | D7 |
| 全部子阶段完整 GitHub 流程 | D0-D7 的 Issue/PR 记录 |

## 10. 非目标与后续扩展

首版不包含自动更新、云端任务、模型下载安装器、WSL 后端、视频编辑器或广义角色自动识别。
这些能力不得阻塞 Issue #190 的本地桌面版验收，但当前的 IPC、store 和队列边界应允许后续
添加，而无需把 Python 业务逻辑搬入 Renderer。
