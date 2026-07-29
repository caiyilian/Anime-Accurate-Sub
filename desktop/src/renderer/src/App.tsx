import { useCallback, useEffect, useState } from 'react'
import type { DiagnosticCheck, DiagnosticsResult, PipelineSettings } from '../../shared/types'

const navigation = ['工作台', '运行记录', '设置']

function CheckCard({ check }: { check: DiagnosticCheck }): React.JSX.Element {
  const colors = {
    ok: 'border-emerald-400/20 bg-emerald-400/5 text-emerald-300',
    warning: 'border-amber-400/20 bg-amber-400/5 text-amber-300',
    error: 'border-rose-400/20 bg-rose-400/5 text-rose-300'
  }
  return (
    <article className={`rounded-2xl border p-4 ${colors[check.status]}`}>
      <div className="flex items-center justify-between gap-3">
        <h4 className="font-medium text-slate-100">{check.label}</h4>
        <span className="text-xs uppercase">{check.status}</span>
      </div>
      <p className="mt-2 text-sm text-slate-400">{check.detail}</p>
      {check.path && <p className="mt-2 truncate font-mono text-xs text-slate-500">{check.path}</p>}
    </article>
  )
}

function PathField({
  label,
  value,
  onChange,
  onPick,
  placeholder
}: {
  label: string
  value: string
  onChange: (value: string) => void
  onPick: () => void
  placeholder: string
}): React.JSX.Element {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-medium text-slate-300">{label}</span>
      <span className="flex gap-2">
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="min-w-0 flex-1 rounded-xl border border-white/10 bg-slate-950 px-3 py-2.5 font-mono text-sm outline-none transition focus:border-cyan-400/50"
        />
        <button type="button" onClick={onPick} className="rounded-xl border border-white/10 px-4 text-sm hover:bg-white/5">
          浏览
        </button>
      </span>
    </label>
  )
}

export default function App(): React.JSX.Element {
  const runtime = window.desktopApi
  const [settings, setSettings] = useState<PipelineSettings | null>(null)
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResult | null>(null)
  const [message, setMessage] = useState('正在读取桌面设置…')
  const [busy, setBusy] = useState(false)

  const diagnose = useCallback(async (): Promise<void> => {
    setBusy(true)
    setMessage('正在诊断 Python、FFmpeg 和项目文件…')
    try {
      const result = await runtime.runDiagnostics()
      setDiagnostics(result)
      setMessage(result.ready ? '环境已就绪，可以进入管线配置。' : '环境仍有阻塞项，请检查红色卡片。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }, [runtime])

  useEffect(() => {
    runtime
      .getSettings()
      .then((value) => {
        setSettings(value)
        return diagnose()
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : String(error)))
  }, [diagnose, runtime])

  const updatePath = (field: 'projectRoot' | 'pythonPath' | 'outputRoot', value: string): void => {
    setSettings((current) => (current ? { ...current, [field]: value } : current))
  }

  const pickDirectory = async (field: 'projectRoot' | 'outputRoot'): Promise<void> => {
    const path = await runtime.pickDirectory()
    if (path) updatePath(field, path)
  }

  const save = async (): Promise<void> => {
    if (!settings) return
    setBusy(true)
    try {
      const saved = await runtime.saveSettings(settings)
      setSettings(saved)
      setMessage('设置已保存。')
      await diagnose()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const reset = async (): Promise<void> => {
    const value = await runtime.resetSettings()
    setSettings(value)
    setMessage('已恢复自动发现设置。')
    await diagnose()
  }

  return (
    <div data-testid="desktop-root" className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-white/10 bg-slate-950/90 px-7 py-5 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-cyan-400 to-indigo-500 font-black text-slate-950">
              字
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">Anime Accurate Sub</h1>
              <p className="text-xs text-slate-400">动画字幕全流程工作台</p>
            </div>
          </div>
          <nav aria-label="主导航" className="flex items-center gap-2">
            {navigation.map((item, index) => (
              <span
                key={item}
                className={`rounded-lg px-3 py-2 text-sm ${index === 0 ? 'bg-white/10 text-white' : 'text-slate-400'}`}
              >
                {item}
              </span>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-7 py-9">
        <section className="rounded-3xl border border-white/10 bg-white/[0.035] p-8 shadow-2xl shadow-indigo-950/30">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-cyan-400/25 bg-cyan-400/10 px-3 py-1 text-xs font-medium text-cyan-300">
            <span className="size-2 rounded-full bg-emerald-300" />
            D2 / Secure platform services
          </div>
          <h2 className="text-3xl font-semibold tracking-tight">设置与运行环境</h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
            路径留空时会自动发现项目和 Python。所有文件系统与进程能力都留在主进程，渲染界面只使用类型化白名单调用。
          </p>
          <dl className="mt-6 grid gap-3 sm:grid-cols-3">
            {[
              ['Electron', runtime.versions.electron],
              ['Chromium', runtime.versions.chrome],
              ['Platform', runtime.platform]
            ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-white/10 bg-slate-900/70 p-4">
                <dt className="text-xs uppercase tracking-wider text-slate-500">{label}</dt>
                <dd className="mt-2 font-mono text-sm text-slate-200">{value}</dd>
              </div>
            ))}
          </dl>

          {settings && (
            <div className="mt-8 grid gap-5 lg:grid-cols-3">
              <PathField
                label="项目根目录"
                value={settings.projectRoot}
                onChange={(value) => updatePath('projectRoot', value)}
                onPick={() => void pickDirectory('projectRoot')}
                placeholder="自动发现（推荐）"
              />
              <PathField
                label="Python 可执行文件"
                value={settings.pythonPath}
                onChange={(value) => updatePath('pythonPath', value)}
                onPick={async () => {
                  const path = await runtime.pickFile('python')
                  if (path) updatePath('pythonPath', path)
                }}
                placeholder="自动发现 .venv / Miniconda / PATH"
              />
              <PathField
                label="默认输出目录"
                value={settings.outputRoot}
                onChange={(value) => updatePath('outputRoot', value)}
                onPick={() => void pickDirectory('outputRoot')}
                placeholder="项目/output/desktop"
              />
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button disabled={busy || !settings} onClick={() => void save()} className="rounded-xl bg-cyan-400 px-5 py-2.5 text-sm font-semibold text-slate-950 disabled:opacity-40">
              保存并诊断
            </button>
            <button disabled={busy} onClick={() => void diagnose()} className="rounded-xl border border-white/10 px-5 py-2.5 text-sm hover:bg-white/5 disabled:opacity-40">
              重新诊断
            </button>
            <button disabled={busy} onClick={() => void reset()} className="rounded-xl px-4 py-2.5 text-sm text-slate-400 hover:text-white disabled:opacity-40">
              恢复自动发现
            </button>
            <p role="status" className="ml-auto text-sm text-slate-400">{message}</p>
          </div>
        </section>

        <section className="mt-6 rounded-3xl border border-white/10 bg-slate-900/40 p-7">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">环境诊断</h3>
            {diagnostics && (
              <span className={`rounded-full px-3 py-1 text-xs ${diagnostics.ready ? 'bg-emerald-400/10 text-emerald-300' : 'bg-rose-400/10 text-rose-300'}`}>
                {diagnostics.ready ? 'READY' : 'BLOCKED'}
              </span>
            )}
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {diagnostics?.checks.map((check) => <CheckCard key={check.id} check={check} />)}
          </div>
          {diagnostics?.logPath && <p className="mt-5 truncate font-mono text-xs text-slate-500">日志：{diagnostics.logPath}</p>}
        </section>
      </main>
    </div>
  )
}
