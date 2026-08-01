import { BrowserWindow, dialog, net, protocol, shell } from 'electron'
import { writeFile } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import type { PipelineSnapshot } from '../shared/types'
import { formatPipelineLog, ResultRegistry } from './result-registry'

export class ResultService {
  readonly registry = new ResultRegistry()

  registerProtocol(): void {
    protocol.handle('aas-media', async (request) => {
      const url = new URL(request.url)
      if (url.hostname !== 'artifact') return new Response('Not found', { status: 404 })
      const id = decodeURIComponent(url.pathname.slice(1))
      if (!/^[a-f0-9]{32}$/.test(id)) return new Response('Not found', { status: 404 })
      try {
        const fileUrl = pathToFileURL(this.registry.getVideoPath(id)).toString()
        const range = request.headers.get('range')
        return net.fetch(fileUrl, range ? { headers: { range } } : undefined)
      } catch {
        return new Response('Not found', { status: 404 })
      }
    })
  }

  async openDirectory(jobId: string): Promise<void> {
    const error = await shell.openPath(this.registry.getDirectory(jobId))
    if (error) throw new Error(error)
  }

  async exportLog(
    snapshot: PipelineSnapshot | null,
    window: BrowserWindow
  ): Promise<string | null> {
    if (!snapshot) throw new Error('没有可导出的运行日志')
    const result = await dialog.showSaveDialog(window, {
      title: '导出运行日志',
      defaultPath: `anime-accurate-sub-${snapshot.runId.slice(0, 8)}.log`,
      filters: [{ name: '日志文本', extensions: ['log', 'txt'] }]
    })
    if (result.canceled || !result.filePath) return null
    await writeFile(result.filePath, formatPipelineLog(snapshot), 'utf8')
    return result.filePath
  }
}
