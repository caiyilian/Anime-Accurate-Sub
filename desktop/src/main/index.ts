import { app, BrowserWindow } from 'electron'
import { registerIpcHandlers } from './ipc'
import { initializeLogging, log } from './logging'
import { createSettingsRepository } from './settings'
import { createMainWindow } from './windows'

const isSmokeTest = process.argv.includes('--smoke-test')
let smokeTimer: NodeJS.Timeout | undefined
let mainWindow: BrowserWindow | null = null
let unregisterIpc: (() => void) | undefined

function attachSmokeTest(window: BrowserWindow): void {
  if (isSmokeTest) {
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
          return {
            root: Boolean(document.querySelector('[data-testid="desktop-root"]')),
            title: document.title,
            text,
            diagnosticsSettled: !text.includes('正在读取桌面设置') && !text.includes('正在诊断'),
            hasNodeRequire: typeof window.require !== 'undefined',
            hasDesktopApi: Boolean(window.desktopApi?.versions?.electron && window.desktopApi?.getSettings)
          }
        })()`)
        if (
          !result.root ||
          result.title !== 'Anime Accurate Sub' ||
          !result.text.includes('设置与运行环境') ||
          !result.diagnosticsSettled ||
          result.hasNodeRequire ||
          !result.hasDesktopApi
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
    unregisterIpc = registerIpcHandlers({ getWindow: () => mainWindow, settings, logPath })
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

app.on('will-quit', () => unregisterIpc?.())
