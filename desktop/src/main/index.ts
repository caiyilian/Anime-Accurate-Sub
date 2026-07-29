import { app, BrowserWindow, protocol } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc'
import { buildPipelineCommand } from './command'
import { runDiagnostics } from './diagnostics'
import { registerIpcHandlers } from './ipc'
import { initializeLogging, log } from './logging'
import { PipelineManager } from './pipeline-manager'
import { createPipelineSnapshotStore } from './run-store'
import { ResultService } from './result-service'
import { createSettingsRepository } from './settings'
import { createMainWindow } from './windows'

const isSmokeTest = process.argv.includes('--smoke-test')
protocol.registerSchemesAsPrivileged([
  { scheme: 'aas-media', privileges: { secure: true, standard: true, stream: true, supportFetchAPI: true } }
])
let smokeTimer: NodeJS.Timeout | undefined
let mainWindow: BrowserWindow | null = null
let unregisterIpc: (() => void) | undefined
let pipelineManager: PipelineManager | undefined

function attachSmokeTest(window: BrowserWindow): void {
  if (isSmokeTest) {
    const smokeVideo = process.env.DESKTOP_SMOKE_VIDEO ?? ''
    smokeTimer = setTimeout(() => {
      console.error('DESKTOP_SMOKE_TIMEOUT')
      app.exit(1)
    }, 15_000)

    window.webContents.once('did-finish-load', async () => {
      try {
        const result = await window.webContents.executeJavaScript(`(async () => {
          for (let attempt = 0; attempt < 100; attempt += 1) {
            const status = document.querySelector('[role="status"]')?.textContent || ''
            if (status && !status.includes('正在')) break
            await new Promise((resolve) => setTimeout(resolve, 100))
          }
          const text = document.body.innerText
          let videoIntegration = null
          const smokeVideo = ${JSON.stringify(smokeVideo)}
          if (smokeVideo) {
            const inspection = await window.desktopApi.inspectVideos([smokeVideo])
            const command = inspection.videos.length
              ? await window.desktopApi.previewCommand({ videoPath: inspection.videos[0].path })
              : null
            videoIntegration = {
              accepted: inspection.videos.length,
              rejected: inspection.rejected.length,
              hasQuality: Boolean(command?.args.includes('--quality-check')),
              hasMultiAgent: Boolean(command?.args.includes('--multi-agent-review')),
              hasMqm: Boolean(command?.args.includes('--mqm-quality-review'))
            }
          }
          return {
            root: Boolean(document.querySelector('[data-testid="desktop-root"]')),
            title: document.title,
            text,
            diagnosticsSettled: !text.includes('正在读取桌面设置') && !text.includes('正在诊断'),
            hasNodeRequire: typeof window.require !== 'undefined',
            hasDesktopApi: Boolean(
              window.desktopApi?.versions?.electron &&
                window.desktopApi?.getSettings &&
                window.desktopApi?.startPipeline &&
                window.desktopApi?.resumePipeline &&
                window.desktopApi?.listResults &&
                window.desktopApi?.readResultArtifact
            ),
            videoIntegration
          }
        })()`)
        if (
          !result.root ||
          result.title !== 'Anime Accurate Sub' ||
          !result.text.includes('字幕生成工作台') ||
          !result.diagnosticsSettled ||
          result.hasNodeRequire ||
          !result.hasDesktopApi ||
          (smokeVideo &&
            (!result.videoIntegration ||
              result.videoIntegration.accepted !== 1 ||
              result.videoIntegration.rejected !== 0 ||
              !result.videoIntegration.hasQuality ||
              !result.videoIntegration.hasMultiAgent ||
              !result.videoIntegration.hasMqm))
        ) {
          throw new Error(`Unexpected renderer state: ${JSON.stringify(result)}`)
        }
        console.log(`DESKTOP_SMOKE_OK ${JSON.stringify(result)}`)
        if (smokeTimer) clearTimeout(smokeTimer)
        app.exit(0)
      } catch (error) {
        console.error('DESKTOP_SMOKE_FAILED', error)
        if (smokeTimer) clearTimeout(smokeTimer)
        app.exit(1)
      }
    })
  }

}

const hasSingleInstanceLock = app.requestSingleInstanceLock()

if (!hasSingleInstanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const window = BrowserWindow.getAllWindows()[0]
    if (window) {
      if (window.isMinimized()) window.restore()
      window.focus()
    }
  })

  app.whenReady().then(() => {
    const logPath = initializeLogging()
    const settings = createSettingsRepository()
    mainWindow = createMainWindow(!isSmokeTest)
    pipelineManager = new PipelineManager({
      store: createPipelineSnapshotStore(),
      commandFactory: async (job) => {
        const diagnostics = await runDiagnostics(job.settings, {
          appPath: app.getAppPath(),
          resourcesPath: process.resourcesPath,
          logPath
        })
        if (!diagnostics.ready) throw new Error('恢复任务前的环境诊断未通过')
        return buildPipelineCommand(
          {
            videoPath: job.video.path,
            japaneseSubtitlePath: job.japaneseSubtitlePath || undefined,
            settings: job.settings
          },
          job.settings,
          diagnostics
        )
      },
      emit: (event) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send(IPC_CHANNELS.pipelineEvent, event)
        }
      }
    })
    const results = new ResultService()
    results.registerProtocol()
    unregisterIpc = registerIpcHandlers({
      getWindow: () => mainWindow,
      settings,
      pipeline: pipelineManager,
      results,
      logPath
    })
    attachSmokeTest(mainWindow)
    mainWindow.once('closed', () => {
      mainWindow = null
    })
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        mainWindow = createMainWindow(true)
      }
    })
  }).catch((error) => {
    log.error('Desktop startup failed', error)
    app.exit(1)
  })
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

let shutdownInProgress = false
app.on('before-quit', (event) => {
  if (shutdownInProgress) return
  event.preventDefault()
  shutdownInProgress = true
  const shutdown = pipelineManager?.shutdown() ?? Promise.resolve()
  void shutdown.finally(() => app.quit())
})
app.on('will-quit', () => unregisterIpc?.())
