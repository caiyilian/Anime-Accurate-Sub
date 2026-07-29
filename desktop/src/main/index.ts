import { app, BrowserWindow } from 'electron'
import { join } from 'node:path'

const isSmokeTest = process.argv.includes('--smoke-test')
let smokeTimer: NodeJS.Timeout | undefined

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1240,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    show: !isSmokeTest,
    backgroundColor: '#080d19',
    title: 'Anime Accurate Sub',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })

  if (process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    void window.loadFile(join(__dirname, '../renderer/index.html'))
  }

  if (isSmokeTest) {
    smokeTimer = setTimeout(() => {
      console.error('DESKTOP_SMOKE_TIMEOUT')
      app.exit(1)
    }, 15_000)

    window.webContents.once('did-finish-load', async () => {
      try {
        const result = await window.webContents.executeJavaScript(`({
          root: Boolean(document.querySelector('[data-testid="desktop-root"]')),
          title: document.title,
          text: document.body.innerText,
          hasNodeRequire: typeof window.require !== 'undefined',
          hasDesktopApi: Boolean(window.desktopApi?.versions?.electron)
        })`)
        if (
          !result.root ||
          result.title !== 'Anime Accurate Sub' ||
          !result.text.includes('桌面端基础框架已就绪') ||
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

  return window
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
    createWindow()
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow()
    })
  })
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
