import { app, BrowserWindow, dialog, ipcMain, type IpcMainInvokeEvent } from 'electron'
import { existsSync } from 'node:fs'
import { extname, isAbsolute, normalize } from 'node:path'
import { IPC_CHANNELS } from '../shared/ipc'
import type { CommandPreviewRequest, FilePickerKind, StartPipelineRequest } from '../shared/types'
import { buildPipelineCommand } from './command'
import { runDiagnostics } from './diagnostics'
import { log } from './logging'
import type { SettingsRepository } from './settings'
import { sanitizeSettings } from './settings'
import { inspectVideoPaths } from './videos'
import type { PipelineJobInput, PipelineManager } from './pipeline-manager'

interface IpcDependencies {
  getWindow: () => BrowserWindow | null
  settings: SettingsRepository
  pipeline: PipelineManager
  logPath: string
}

export function isTrustedIpcSender(
  event: Pick<IpcMainInvokeEvent, 'sender' | 'senderFrame'>,
  trustedWebContentsId: number
): boolean {
  return (
    event.sender.id === trustedWebContentsId &&
    Boolean(event.senderFrame) &&
    event.senderFrame?.parent === null
  )
}

function trustedHandler<TArgs extends unknown[], TResult>(
  dependencies: IpcDependencies,
  handler: (event: IpcMainInvokeEvent, ...args: TArgs) => TResult | Promise<TResult>
): (event: IpcMainInvokeEvent, ...args: TArgs) => TResult | Promise<TResult> {
  return (event, ...args) => {
    const window = dependencies.getWindow()
    if (!window || !isTrustedIpcSender(event, window.webContents.id)) {
      throw new Error('拒绝来自非主窗口的 IPC 调用')
    }
    return handler(event, ...args)
  }
}

const filters: Record<FilePickerKind, Electron.FileFilter[]> = {
  json: [{ name: 'JSON', extensions: ['json', 'jsonl'] }],
  python: [{ name: 'Python', extensions: ['exe'] }],
  subtitle: [{ name: '字幕', extensions: ['srt', 'ass', 'vtt'] }],
  video: [{ name: '视频', extensions: ['mp4', 'mkv', 'avi', 'mov', 'webm'] }]
}

function normalizeExistingPaths(paths: string[]): string[] {
  return paths.filter((path) => existsSync(path)).map((path) => normalize(path))
}

export function registerIpcHandlers(dependencies: IpcDependencies): () => void {
  const register = <TArgs extends unknown[], TResult>(
    channel: string,
    handler: (event: IpcMainInvokeEvent, ...args: TArgs) => TResult | Promise<TResult>
  ): void => ipcMain.handle(channel, trustedHandler(dependencies, handler))

  register(IPC_CHANNELS.getSettings, () => dependencies.settings.get())
  register(IPC_CHANNELS.saveSettings, (_event, value) => {
    const saved = dependencies.settings.save(value)
    log.info('Desktop settings saved', {
      backend: saved.backend,
      qualityCheck: saved.qualityCheck,
      multiAgentReview: saved.multiAgentReview,
      mqmQualityReview: saved.mqmQualityReview
    })
    return saved
  })
  register(IPC_CHANNELS.resetSettings, () => dependencies.settings.reset())
  register(IPC_CHANNELS.pickVideos, async () => {
    const result = await dialog.showOpenDialog(dependencies.getWindow()!, {
      title: '选择动画视频',
      properties: ['openFile', 'multiSelections'],
      filters: filters.video
    })
    return result.canceled ? [] : normalizeExistingPaths(result.filePaths)
  })
  register(IPC_CHANNELS.pickFile, async (_event, kind: FilePickerKind) => {
    if (!Object.hasOwn(filters, kind)) throw new TypeError('未知文件选择类型')
    const result = await dialog.showOpenDialog(dependencies.getWindow()!, {
      title: '选择文件',
      properties: ['openFile'],
      filters: filters[kind]
    })
    return result.canceled ? null : normalizeExistingPaths(result.filePaths)[0] ?? null
  })
  register(IPC_CHANNELS.pickDirectory, async () => {
    const result = await dialog.showOpenDialog(dependencies.getWindow()!, {
      title: '选择目录',
      properties: ['openDirectory', 'createDirectory']
    })
    return result.canceled ? null : normalize(result.filePaths[0])
  })
  register(IPC_CHANNELS.inspectVideos, (_event, paths) => inspectVideoPaths(paths))
  register(IPC_CHANNELS.runDiagnostics, async () => {
    const result = await runDiagnostics(dependencies.settings.get(), {
      appPath: app.getAppPath(),
      resourcesPath: process.resourcesPath,
      logPath: dependencies.logPath
    })
    log.info('Environment diagnostics completed', {
      ready: result.ready,
      checks: result.checks.map((check) => `${check.id}:${check.status}`)
    })
    return result
  })
  register(IPC_CHANNELS.previewCommand, async (_event, request: CommandPreviewRequest) => {
    if (!request || typeof request !== 'object') throw new TypeError('命令预览请求无效')
    const diagnostics = await runDiagnostics(dependencies.settings.get(), {
      appPath: app.getAppPath(),
      resourcesPath: process.resourcesPath,
      logPath: dependencies.logPath
    })
    const preview = buildPipelineCommand(request, dependencies.settings.get(), diagnostics)
    log.info('Pipeline command preview generated', {
      executable: preview.executable,
      cwd: preview.cwd,
      videoExtension: extname(request.videoPath)
    })
    return preview
  })
  register(IPC_CHANNELS.startPipeline, async (_event, request: StartPipelineRequest) => {
    if (!request || typeof request !== 'object' || !Array.isArray(request.videos)) {
      throw new TypeError('启动请求无效')
    }
    const settings = sanitizeSettings(request.settings)
    const inspection = await inspectVideoPaths(request.videos.map((video) => video?.path))
    if (inspection.rejected.length || inspection.videos.length !== request.videos.length) {
      throw new TypeError(
        `视频队列校验失败：${inspection.rejected.map((item) => `${item.path}: ${item.reason}`).join('；')}`
      )
    }
    const diagnostics = await runDiagnostics(settings, {
      appPath: app.getAppPath(),
      resourcesPath: process.resourcesPath,
      logPath: dependencies.logPath
    })
    if (!diagnostics.ready) {
      const blockers = diagnostics.checks.filter((check) => check.status === 'error').map((check) => check.label)
      throw new Error(`运行环境未就绪：${blockers.join('、')}`)
    }
    const inputs: PipelineJobInput[] = inspection.videos.map((video, index) => {
      const japaneseSubtitlePath = request.videos[index].japaneseSubtitlePath?.trim() ?? ''
      if (
        japaneseSubtitlePath &&
        (!isAbsolute(japaneseSubtitlePath) ||
          !existsSync(japaneseSubtitlePath) ||
          !['.srt', '.ass', '.vtt'].includes(extname(japaneseSubtitlePath).toLocaleLowerCase('en-US')))
      ) {
        throw new TypeError(`日文字幕路径无效：${japaneseSubtitlePath}`)
      }
      buildPipelineCommand(
        { videoPath: video.path, japaneseSubtitlePath: japaneseSubtitlePath || undefined, settings },
        settings,
        diagnostics
      )
      return { video, japaneseSubtitlePath: japaneseSubtitlePath ? normalize(japaneseSubtitlePath) : '', settings }
    })
    return dependencies.pipeline.start(inputs, settings.continueOnError)
  })
  register(IPC_CHANNELS.cancelPipeline, () => dependencies.pipeline.cancel())
  register(IPC_CHANNELS.resumePipeline, () => dependencies.pipeline.resume())
  register(IPC_CHANNELS.getPipelineSnapshot, () => dependencies.pipeline.getSnapshot())

  return () => {
    for (const channel of Object.values(IPC_CHANNELS)) {
      if (channel !== IPC_CHANNELS.pipelineEvent) ipcMain.removeHandler(channel)
    }
  }
}
