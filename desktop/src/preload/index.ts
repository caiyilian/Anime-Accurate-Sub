import { contextBridge, ipcRenderer, webUtils } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc'
import type { CommandPreviewRequest, DesktopApi, FilePickerKind, PipelineSettings } from '../shared/types'

const desktopApi: Readonly<DesktopApi> = Object.freeze({
  platform: process.platform,
  versions: Object.freeze({
    chrome: process.versions.chrome,
    electron: process.versions.electron,
    node: process.versions.node
  }),
  getSettings: () => ipcRenderer.invoke(IPC_CHANNELS.getSettings),
  saveSettings: (settings: PipelineSettings) => ipcRenderer.invoke(IPC_CHANNELS.saveSettings, settings),
  resetSettings: () => ipcRenderer.invoke(IPC_CHANNELS.resetSettings),
  pickVideos: () => ipcRenderer.invoke(IPC_CHANNELS.pickVideos),
  pickFile: (kind: FilePickerKind) => ipcRenderer.invoke(IPC_CHANNELS.pickFile, kind),
  pickDirectory: () => ipcRenderer.invoke(IPC_CHANNELS.pickDirectory),
  getPathForFile: (file: unknown) => webUtils.getPathForFile(file as File),
  inspectVideos: (paths: string[]) => ipcRenderer.invoke(IPC_CHANNELS.inspectVideos, paths),
  runDiagnostics: () => ipcRenderer.invoke(IPC_CHANNELS.runDiagnostics),
  previewCommand: (request: CommandPreviewRequest) => ipcRenderer.invoke(IPC_CHANNELS.previewCommand, request)
})

contextBridge.exposeInMainWorld('desktopApi', desktopApi)
