import type { PipelineSnapshot } from '../../shared/types'

function ProgressBar({
  value,
  tone = 'cyan'
}: {
  value: number
  tone?: 'cyan' | 'emerald'
}): React.JSX.Element {
  const color = tone === 'emerald' ? 'bg-emerald-400' : 'bg-cyan-400'
  return (
    <div
      className="h-2 overflow-hidden rounded-full bg-white/8"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
    >
      <div
        className={`h-full rounded-full transition-[width] duration-300 ${color}`}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  )
}

export default function PipelineProgress({
  snapshot
}: {
  snapshot: PipelineSnapshot
}): React.JSX.Element {
  const current = snapshot.jobs.find((job) => job.id === snapshot.currentJobId)
  return (
    <section className="mt-6 rounded-3xl border border-white/10 bg-slate-900/45 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-violet-300">
            04 / 实时进度
          </p>
          <h2 className="mt-2 text-lg font-semibold">
            {current ? current.video.name : `队列 ${snapshot.status}`}
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            {current
              ? `${current.progress.activeStageLabel} · ${current.progress.stagePercent.toFixed(1)}%`
              : '当前没有运行中的视频'}
          </p>
        </div>
        <span className="font-mono text-2xl text-cyan-300">
          {snapshot.overallPercent.toFixed(1)}%
        </span>
      </div>
      <div className="mt-4">
        <ProgressBar value={snapshot.overallPercent} />
      </div>

      {current && (
        <ol className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-5" aria-label="当前任务阶段">
          {current.progress.stages.map((stage) => (
            <li
              key={stage.key}
              className={`rounded-xl border px-3 py-2 text-xs ${stage.status === 'completed' ? 'border-emerald-400/15 bg-emerald-400/5 text-emerald-300' : stage.status === 'running' ? 'border-cyan-400/30 bg-cyan-400/8 text-cyan-200' : stage.status === 'failed' ? 'border-rose-400/25 bg-rose-400/8 text-rose-300' : 'border-white/8 text-slate-500'}`}
            >
              <div className="flex justify-between gap-2">
                <span>{stage.label}</span>
                <span>{stage.percent.toFixed(0)}%</span>
              </div>
            </li>
          ))}
        </ol>
      )}

      <div className="mt-5 space-y-3">
        {snapshot.jobs.map((job, index) => (
          <article
            key={job.id}
            className="grid items-center gap-3 sm:grid-cols-[2rem_minmax(0,1fr)_6rem]"
          >
            <span className="font-mono text-xs text-slate-600">
              {String(index + 1).padStart(2, '0')}
            </span>
            <div className="min-w-0">
              <div className="mb-1.5 flex justify-between gap-3 text-xs">
                <span className="truncate text-slate-300">{job.video.name}</span>
                <span className="font-mono text-slate-500">
                  {job.progress.overallPercent.toFixed(1)}%
                </span>
              </div>
              <ProgressBar
                value={job.progress.overallPercent}
                tone={job.status === 'succeeded' ? 'emerald' : 'cyan'}
              />
            </div>
            <span className="text-right text-xs uppercase text-slate-500">{job.status}</span>
          </article>
        ))}
      </div>
    </section>
  )
}
