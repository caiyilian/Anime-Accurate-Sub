import { contextBridge, ipcRenderer, webUtils } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc'
import type {
  CommandPreviewRequest,
  DesktopApi,
  FilePickerKind,
  PipelineEvent,
  PipelineSettings,
  StartPipelineRequest
} from '../shared/types'

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
  previewCommand: (request: CommandPreviewRequest) => ipcRenderer.invoke(IPC_CHANNELS.previewCommand, request),
  startPipeline: (request: StartPipelineRequest) => ipcRenderer.invoke(IPC_CHANNELS.startPipeline, request),
  cancelPipeline: () => ipcRenderer.invoke(IPC_CHANNELS.cancelPipeline),
  resumePipeline: () => ipcRenderer.invoke(IPC_CHANNELS.resumePipeline),
  getPipelineSnapshot: () => ipcRenderer.invoke(IPC_CHANNELS.getPipelineSnapshot),
  onPipelineEvent: (listener: (event: PipelineEvent) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, value: PipelineEvent): void => listener(value)
    ipcRenderer.on(IPC_CHANNELS.pipelineEvent, handler)
    return () => ipcRenderer.removeListener(IPC_CHANNELS.pipelineEvent, handler)
  }
})

contextBridge.exposeInMainWorld('desktopApi', desktopApi)
