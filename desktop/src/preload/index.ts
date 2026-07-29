import { contextBridge } from 'electron'

const desktopApi = Object.freeze({
  platform: process.platform,
  versions: Object.freeze({
    chrome: process.versions.chrome,
    electron: process.versions.electron,
    node: process.versions.node
  })
})

contextBridge.exposeInMainWorld('desktopApi', desktopApi)
