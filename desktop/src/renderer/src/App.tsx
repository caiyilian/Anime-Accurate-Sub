const navigation = ['工作台', '运行记录', '设置']

export default function App(): React.JSX.Element {
  const runtime = window.desktopApi

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

      <main className="mx-auto grid min-h-[calc(100vh-81px)] max-w-7xl place-items-center px-7 py-12">
        <section className="w-full max-w-3xl rounded-3xl border border-white/10 bg-white/[0.035] p-10 shadow-2xl shadow-indigo-950/30">
          <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
            <span className="size-2 rounded-full bg-emerald-300" />
            D1 / Desktop shell
          </div>
          <h2 className="text-4xl font-semibold tracking-tight">桌面端基础框架已就绪</h2>
          <p className="mt-4 max-w-2xl text-base leading-7 text-slate-400">
            Electron 主进程、隔离预加载层和 React 渲染进程已经连通。后续阶段将在这个安全边界内接入视频队列、Python 管线和结果预览。
          </p>
          <dl className="mt-9 grid gap-3 sm:grid-cols-3">
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
        </section>
      </main>
    </div>
  )
}
