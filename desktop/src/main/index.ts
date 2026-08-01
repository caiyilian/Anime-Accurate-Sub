import { app, BrowserWindow, protocol } from 'electron'
import { resolve } from 'node:path'
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
const pipelineSmoke = {
  videoPath: process.env.DESKTOP_PIPELINE_SMOKE_VIDEO ?? '',
  japaneseSubtitlePath: process.env.DESKTOP_PIPELINE_SMOKE_SUBTITLE ?? '',
  projectRoot: process.env.DESKTOP_PIPELINE_SMOKE_PROJECT_ROOT ?? '',
  pythonPath: process.env.DESKTOP_PIPELINE_SMOKE_PYTHON ?? '',
  outputRoot: process.env.DESKTOP_PIPELINE_SMOKE_OUTPUT ?? '',
  translationConfigPath: process.env.DESKTOP_PIPELINE_SMOKE_TRANSLATION_CONFIG ?? '',
  memoryPath: process.env.DESKTOP_PIPELINE_SMOKE_MEMORY ?? '',
  glossaryPath: process.env.DESKTOP_PIPELINE_SMOKE_GLOSSARY ?? '',
  cancelAndResume: process.env.DESKTOP_PIPELINE_SMOKE_CANCEL_RESUME === '1'
}
if (isSmokeTest && process.env.DESKTOP_SMOKE_USER_DATA) {
  app.setPath('userData', resolve(process.env.DESKTOP_SMOKE_USER_DATA))
}
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'aas-media',
    privileges: { secure: true, standard: true, stream: true, supportFetchAPI: true }
  }
])
let smokeTimer: NodeJS.Timeout | undefined
let mainWindow: BrowserWindow | null = null
let unregisterIpc: (() => void) | undefined
let pipelineManager: PipelineManager | undefined

function attachSmokeTest(window: BrowserWindow): void {
  if (isSmokeTest) {
    const smokeVideo = process.env.DESKTOP_SMOKE_VIDEO ?? ''
    const timeoutMs = pipelineSmoke.videoPath
      ? Number(process.env.DESKTOP_PIPELINE_SMOKE_TIMEOUT_MS ?? 2_700_000)
      : 15_000
    smokeTimer = setTimeout(() => {
      console.error('DESKTOP_SMOKE_TIMEOUT')
      app.exit(1)
    }, timeoutMs)

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
          let pipelineIntegration = null
          const smokeVideo = ${JSON.stringify(smokeVideo)}
          const pipelineSmoke = ${JSON.stringify(pipelineSmoke)}
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
          if (pipelineSmoke.videoPath) {
            const originalSettings = await window.desktopApi.getSettings()
            const settings = {
              ...originalSettings,
              projectRoot: pipelineSmoke.projectRoot,
              pythonPath: pipelineSmoke.pythonPath,
              outputRoot: pipelineSmoke.outputRoot,
              backend: 'sakura',
              asrBackend: 'anime_whisper',
              translationConfigPath: pipelineSmoke.translationConfigPath,
              memoryPath: pipelineSmoke.memoryPath,
              glossaryPath: pipelineSmoke.glossaryPath,
              translationBatchSize: 16,
              translationContextWindow: 3,
              preferJapaneseSubtitles: true,
              qualityCheck: true,
              multiAgentReview: true,
              mqmQualityReview: true,
              autoHardware: false,
              opedSeries: '',
              opedBestEffort: true,
              continueOnError: false
            }
            await window.desktopApi.saveSettings(settings)
            const inspection = await window.desktopApi.inspectVideos([pipelineSmoke.videoPath])
            if (inspection.videos.length !== 1) throw new Error('Pipeline smoke video inspection failed')
            await window.desktopApi.startPipeline({
              videos: [{
                path: inspection.videos[0].path,
                japaneseSubtitlePath: pipelineSmoke.japaneseSubtitlePath || undefined
              }],
              settings
            })
            let canceledWithCheckpoint = false
            let resumed = false
            if (pipelineSmoke.cancelAndResume) {
              const checkpointDeadline = Date.now() + 120_000
              while (Date.now() < checkpointDeadline) {
                const bundles = await window.desktopApi.listResults()
                if (bundles.some((bundle) => bundle.artifacts.some((artifact) => artifact.kind === 'checkpoint'))) break
                await new Promise((resolve) => setTimeout(resolve, 500))
              }
              const canceled = await window.desktopApi.cancelPipeline()
              const bundles = await window.desktopApi.listResults()
              canceledWithCheckpoint = Boolean(
                canceled?.status === 'canceled' &&
                bundles.some((bundle) => bundle.artifacts.some((artifact) => artifact.kind === 'checkpoint'))
              )
              if (!canceledWithCheckpoint) throw new Error('Pipeline cancellation did not preserve checkpoint')
              await window.desktopApi.resumePipeline()
              resumed = true
            }
            const deadline = Date.now() + ${JSON.stringify(Number(process.env.DESKTOP_PIPELINE_SMOKE_TIMEOUT_MS ?? 2_700_000))}
            let snapshot = await window.desktopApi.getPipelineSnapshot()
            while (snapshot && ['running', 'canceling'].includes(snapshot.status) && Date.now() < deadline) {
              await new Promise((resolve) => setTimeout(resolve, 1_000))
              snapshot = await window.desktopApi.getPipelineSnapshot()
            }
            const bundles = await window.desktopApi.listResults()
            const kinds = bundles.flatMap((bundle) => bundle.artifacts.map((artifact) => artifact.kind))
            pipelineIntegration = {
              status: snapshot?.status ?? null,
              jobStatus: snapshot?.jobs[0]?.status ?? null,
              exitCode: snapshot?.jobs[0]?.exitCode ?? null,
              overallPercent: snapshot?.overallPercent ?? null,
              kinds,
              canceledWithCheckpoint,
              resumed,
              outputRoot: settings.outputRoot
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
            diagnostics: await window.desktopApi.runDiagnostics(await window.desktopApi.getSettings()),
            videoIntegration,
            pipelineIntegration
          }
        })()`)
        if (
          !result.root ||
          result.title !== 'Anime Accurate Sub' ||
          !result.text.includes('字幕生成工作台') ||
          !result.diagnosticsSettled ||
          result.hasNodeRequire ||
          !result.hasDesktopApi ||
          (process.env.DESKTOP_SMOKE_EXPECT_BACKEND === '1' &&
            !/[\\/]resources[\\/]backend$/.test(result.diagnostics?.resolved?.projectRoot || '')) ||
          (smokeVideo &&
            (!result.videoIntegration ||
              result.videoIntegration.accepted !== 1 ||
              result.videoIntegration.rejected !== 0 ||
              !result.videoIntegration.hasQuality ||
              !result.videoIntegration.hasMultiAgent ||
              !result.videoIntegration.hasMqm)) ||
          (pipelineSmoke.videoPath &&
            (!result.pipelineIntegration ||
              result.pipelineIntegration.status !== 'completed' ||
              result.pipelineIntegration.jobStatus !== 'succeeded' ||
              !['subtitle-srt', 'subtitle-ass', 'video', 'quality-report'].every((kind) =>
                result.pipelineIntegration.kinds.includes(kind)
              ) ||
              (pipelineSmoke.cancelAndResume &&
                (!result.pipelineIntegration.canceledWithCheckpoint ||
                  !result.pipelineIntegration.resumed))))
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

  app
    .whenReady()
    .then(() => {
      const logPath = initializeLogging()
      const settings = createSettingsRepository()
      mainWindow = createMainWindow(!isSmokeTest)
      pipelineManager = new PipelineManager({
        store: createPipelineSnapshotStore(),
        commandFactory: async (job) => {
          const diagnostics = await runDiagnostics(job.settings, {
            appPath: app.getAppPath(),
            resourcesPath: process.resourcesPath,
            userDataPath: app.getPath('userData'),
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
        userDataPath: app.getPath('userData'),
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
    })
    .catch((error) => {
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
