import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  CommandPreview,
  DiagnosticCheck,
  DiagnosticsResult,
  FilePickerKind,
  PipelineSettings
} from '../../shared/types'
import PipelineConfig from './PipelineConfig'
import { mergeVideoQueue, moveQueueItem, type QueuedVideo } from './queue'
import VideoQueue from './VideoQueue'

const navigation = ['工作台', '运行记录', '设置']

function CheckPill({ check }: { check: DiagnosticCheck }): React.JSX.Element {
  const color = {
    ok: 'border-emerald-400/20 bg-emerald-400/8 text-emerald-300',
    warning: 'border-amber-400/20 bg-amber-400/8 text-amber-300',
    error: 'border-rose-400/20 bg-rose-400/8 text-rose-300'
  }[check.status]
  return (
    <span title={`${check.detail}${check.path ? `\n${check.path}` : ''}`} className={`rounded-full border px-3 py-1 text-xs ${color}`}>
      {check.label} · {check.status.toUpperCase()}
    </span>
  )
}

export default function App(): React.JSX.Element {
  const runtime = window.desktopApi
  const [settings, setSettings] = useState<PipelineSettings | null>(null)
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResult | null>(null)
  const [queue, setQueue] = useState<QueuedVideo[]>([])
  const [preview, setPreview] = useState<CommandPreview | null>(null)
  const [previewRevision, setPreviewRevision] = useState(0)
  const [message, setMessage] = useState('正在读取桌面设置…')
  const [busy, setBusy] = useState(false)
  const [dragActive, setDragActive] = useState(false)

  const diagnose = useCallback(async (): Promise<DiagnosticsResult> => {
    const result = await runtime.runDiagnostics()
    setDiagnostics(result)
    return result
  }, [runtime])

  useEffect(() => {
    let active = true
    runtime
      .getSettings()
      .then(async (value) => {
        if (!active) return
        setSettings(value)
        setMessage('正在诊断 Python、FFmpeg 和项目文件…')
        const result = await diagnose()
        if (active) setMessage(result.ready ? '运行环境已就绪。' : '环境仍有阻塞项，请展开设置检查路径。')
      })
      .catch((error) => active && setMessage(error instanceof Error ? error.message : String(error)))
    return () => {
      active = false
    }
  }, [diagnose, runtime])

  const firstVideo = queue[0]
  useEffect(() => {
    if (!firstVideo || !settings) {
      setPreview(null)
      return
    }
    let active = true
    const timer = setTimeout(() => {
      runtime
        .previewCommand({
          videoPath: firstVideo.path,
          japaneseSubtitlePath: firstVideo.japaneseSubtitlePath || undefined,
          settings
        })
        .then((value) => active && setPreview(value))
        .catch((error) => active && setMessage(`命令预览失败：${error instanceof Error ? error.message : String(error)}`))
    }, 250)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [firstVideo?.path, firstVideo?.japaneseSubtitlePath, previewRevision, runtime, settings])

  const addPaths = useCallback(
    async (paths: string[]): Promise<void> => {
      if (!paths.length) return
      setBusy(true)
      try {
        const result = await runtime.inspectVideos(paths)
        const merged = mergeVideoQueue(queue, result.videos)
        setQueue(merged.queue)
        const accepted = result.videos.length - merged.duplicates
        const rejected = result.rejected.length + merged.duplicates
        setMessage(`已加入 ${accepted} 个视频${rejected ? `，忽略 ${rejected} 个无效或重复项` : ''}。`)
      } catch (error) {
        setMessage(error instanceof Error ? error.message : String(error))
      } finally {
        setBusy(false)
      }
    },
    [queue, runtime]
  )

  const browseVideos = async (): Promise<void> => addPaths(await runtime.pickVideos())

  const dropFiles = async (files: File[]): Promise<void> => {
    const paths = files.map((file) => runtime.getPathForFile(file)).filter(Boolean)
    await addPaths(paths)
  }

  const attachSubtitle = async (id: string): Promise<void> => {
    const path = await runtime.pickFile('subtitle')
    if (!path) return
    setQueue((current) => current.map((item) => (item.id === id ? { ...item, japaneseSubtitlePath: path } : item)))
    setMessage('已关联单集日文字幕。')
  }

  const pickDirectory = async (field: 'projectRoot' | 'outputRoot' | 'japaneseSubtitleDir'): Promise<void> => {
    const path = await runtime.pickDirectory()
    if (path) setSettings((current) => (current ? { ...current, [field]: path } : current))
  }

  const pickFile = async (
    field: 'pythonPath' | 'translationConfigPath' | 'memoryPath' | 'glossaryPath' | 'translationMemoryPath' | 'speakerMapPath',
    kind: FilePickerKind
  ): Promise<void> => {
    const path = await runtime.pickFile(kind)
    if (path) setSettings((current) => (current ? { ...current, [field]: path } : current))
  }

  const saveSettings = async (): Promise<void> => {
    if (!settings) return
    setBusy(true)
    try {
      const saved = await runtime.saveSettings(settings)
      setSettings(saved)
      const result = await diagnose()
      setPreviewRevision((value) => value + 1)
      setMessage(result.ready ? '配置已保存并通过环境诊断。' : '配置已保存，但环境仍有阻塞项。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const resetSettings = async (): Promise<void> => {
    setSettings(await runtime.resetSettings())
    setMessage('已恢复质量优先默认设置。')
    setPreviewRevision((value) => value + 1)
  }

  const readySummary = useMemo(() => {
    if (!diagnostics) return 'CHECKING'
    return diagnostics.ready ? 'READY' : 'BLOCKED'
  }, [diagnostics])

  return (
    <div data-testid="desktop-root" className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-20 border-b border-white/10 bg-slate-950/90 px-7 py-4 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-cyan-400 to-indigo-500 font-black text-slate-950">字</div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">Anime Accurate Sub</h1>
              <p className="text-xs text-slate-400">动画字幕全流程工作台</p>
            </div>
          </div>
          <nav aria-label="主导航" className="flex items-center gap-2">
            {navigation.map((item, index) => (
              <span key={item} className={`rounded-lg px-3 py-2 text-sm ${index === 0 ? 'bg-white/10 text-white' : 'text-slate-500'}`}>{item}</span>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] px-7 py-7">
        <section className="mb-6 flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/8 px-3 py-1 text-xs text-cyan-300">D3 / Quality-first workbench</div>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight">字幕生成工作台</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">先排列视频，再启用项目已经完成的上下文、审查和 MQM 能力。参考字幕只用于评测；正式生成不依赖字幕组译文。</p>
          </div>
          <div className="text-right">
            <p className={`font-mono text-sm ${diagnostics?.ready ? 'text-emerald-300' : 'text-amber-300'}`}>{readySummary}</p>
            <p className="mt-1 text-xs text-slate-500">{queue.length} 个视频待处理</p>
          </div>
        </section>

        <section className="mb-5 flex flex-wrap items-center gap-2 rounded-2xl border border-white/10 bg-slate-900/55 px-4 py-3">
          {diagnostics?.checks.map((check) => <CheckPill key={check.id} check={check} />)}
          <p role="status" className="ml-auto text-sm text-slate-400">{message}</p>
        </section>

        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,0.92fr)_minmax(520px,1.08fr)]">
          <VideoQueue
            queue={queue}
            dragActive={dragActive}
            onBrowse={() => void browseVideos()}
            onDrop={(files) => void dropFiles(files)}
            onDragActiveChange={setDragActive}
            onMove={(id, offset) => setQueue((current) => moveQueueItem(current, id, offset))}
            onRemove={(id) => setQueue((current) => current.filter((item) => item.id !== id))}
            onClear={() => setQueue([])}
            onAttachSubtitle={(id) => void attachSubtitle(id)}
          />
          {settings && (
            <PipelineConfig
              settings={settings}
              onChange={setSettings}
              onPickDirectory={(field) => void pickDirectory(field)}
              onPickFile={(field, kind) => void pickFile(field, kind)}
            />
          )}
        </div>

        <section className="mt-6 rounded-3xl border border-white/10 bg-slate-900/45 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">03 / 保存与预览</p>
              <h2 className="mt-2 text-lg font-semibold">实际 Python 命令</h2>
            </div>
            <div className="flex gap-2">
              <button disabled={busy || !settings} onClick={() => void resetSettings()} className="rounded-xl border border-white/10 px-4 py-2 text-sm text-slate-400 hover:bg-white/5 disabled:opacity-40">恢复默认</button>
              <button disabled={busy || !settings} onClick={() => void saveSettings()} className="rounded-xl bg-cyan-400 px-5 py-2 text-sm font-semibold text-slate-950 disabled:opacity-40">保存配置</button>
              <button disabled className="rounded-xl bg-emerald-400 px-5 py-2 text-sm font-semibold text-slate-950 opacity-40" title="D4 接入真实执行">开始完整流程</button>
            </div>
          </div>
          <pre className="mt-4 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-2xl border border-white/8 bg-slate-950 p-4 font-mono text-xs leading-5 text-slate-400">
            {preview?.display ?? (queue.length ? '正在生成命令预览…' : '加入视频后显示首个任务的完整命令；执行时仍使用参数数组，不经过 shell。')}
          </pre>
        </section>
      </main>
    </div>
  )
}
