import { useEffect, useMemo, useRef, useState } from 'react'
import type { PipelineJob, PipelineLogLine } from '../../shared/types'

type LogFilter = 'all' | PipelineLogLine['stream']

export default function LogConsole({
  logs,
  jobs
}: {
  logs: PipelineLogLine[]
  jobs: PipelineJob[]
}): React.JSX.Element {
  const [filter, setFilter] = useState<LogFilter>('all')
  const [query, setQuery] = useState('')
  const [autoFollow, setAutoFollow] = useState(true)
  const [hiddenCount, setHiddenCount] = useState(0)
  const viewport = useRef<HTMLDivElement>(null)
  const jobNames = useMemo(() => new Map(jobs.map((job) => [job.id, job.video.name])), [jobs])
  const visible = useMemo(
    () =>
      logs
        .slice(Math.min(hiddenCount, logs.length))
        .filter(
          (log) =>
            (filter === 'all' || log.stream === filter) &&
            (!query || log.line.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
        ),
    [filter, hiddenCount, logs, query]
  )

  useEffect(() => {
    if (autoFollow && viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight
  }, [autoFollow, visible])

  return (
    <section className="mt-6 rounded-3xl border border-white/10 bg-slate-900/45 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-amber-300">
            05 / 实时日志
          </p>
          <h2 className="mt-2 text-lg font-semibold">Python stdout / stderr</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="日志流筛选"
            value={filter}
            onChange={(event) => setFilter(event.target.value as LogFilter)}
            className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-xs"
          >
            <option value="all">全部</option>
            <option value="stdout">stdout</option>
            <option value="stderr">stderr</option>
            <option value="system">system</option>
          </select>
          <input
            aria-label="搜索日志"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索"
            className="w-36 rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-xs"
          />
          <button
            type="button"
            onClick={() => setAutoFollow((value) => !value)}
            className={`rounded-lg border px-3 py-2 text-xs ${autoFollow ? 'border-cyan-400/30 text-cyan-300' : 'border-white/10 text-slate-400'}`}
          >
            {autoFollow ? '自动跟随：开' : '自动跟随：关'}
          </button>
          <button
            type="button"
            onClick={() => setHiddenCount(logs.length)}
            className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-400"
          >
            清空视图
          </button>
        </div>
      </div>
      <div
        ref={viewport}
        className="mt-4 h-72 overflow-auto rounded-2xl border border-white/8 bg-[#050810] p-4 font-mono text-xs leading-5"
        aria-label="实时管线日志"
      >
        {visible.length === 0 && <p className="text-slate-600">暂无符合条件的日志。</p>}
        {visible.map((log, index) => (
          <div
            key={`${log.at}-${log.jobId}-${index}`}
            className={
              log.stream === 'stderr'
                ? 'text-rose-300'
                : log.stream === 'system'
                  ? 'text-amber-300'
                  : 'text-slate-400'
            }
          >
            <span className="text-slate-700">{new Date(log.at).toLocaleTimeString()} </span>
            <span className="text-slate-600">
              [{jobNames.get(log.jobId) ?? log.jobId}] [{log.stream}]{' '}
            </span>
            <span className="whitespace-pre-wrap break-all">{log.line}</span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-right text-xs text-slate-600">
        显示 {visible.length} / 快照保留 {logs.length} 行
      </p>
    </section>
  )
}
