import { formatFileSize, type QueuedVideo } from './queue'

interface VideoQueueProps {
  queue: QueuedVideo[]
  dragActive: boolean
  onBrowse: () => void
  onDrop: (files: File[]) => void
  onDragActiveChange: (active: boolean) => void
  onMove: (id: string, offset: -1 | 1) => void
  onRemove: (id: string) => void
  onClear: () => void
  onAttachSubtitle: (id: string) => void
  statuses?: Record<string, string>
  locked?: boolean
}

export default function VideoQueue({
  queue,
  dragActive,
  onBrowse,
  onDrop,
  onDragActiveChange,
  onMove,
  onRemove,
  onClear,
  onAttachSubtitle,
  statuses = {},
  locked = false
}: VideoQueueProps): React.JSX.Element {
  return (
    <section className="rounded-3xl border border-white/10 bg-white/[0.035] p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-cyan-300">01 / 视频队列</p>
          <h2 className="mt-2 text-xl font-semibold">按顺序处理多集动画</h2>
        </div>
        {queue.length > 0 && (
          <button type="button" disabled={locked} onClick={onClear} className="text-sm text-slate-400 hover:text-rose-300 disabled:opacity-30">
            清空
          </button>
        )}
      </div>

      <button
        data-testid="video-drop-zone"
        type="button"
        onClick={() => !locked && onBrowse()}
        onDragEnter={(event) => {
          event.preventDefault()
          onDragActiveChange(true)
        }}
        onDragOver={(event) => {
          event.preventDefault()
          event.dataTransfer.dropEffect = 'copy'
          onDragActiveChange(true)
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onDragActiveChange(false)
        }}
        onDrop={(event) => {
          event.preventDefault()
          onDragActiveChange(false)
          if (!locked) onDrop(Array.from(event.dataTransfer.files))
        }}
        className={`mt-5 w-full rounded-2xl border border-dashed px-6 py-8 text-center transition ${
          dragActive
            ? 'border-cyan-300 bg-cyan-300/10 text-cyan-200'
            : 'border-white/15 bg-slate-950/50 text-slate-400 hover:border-cyan-400/40 hover:text-slate-200'
        }`}
      >
        <span className="block text-base font-medium">{locked ? '管线运行中，队列已锁定' : '拖放 MP4 / MKV，或点击选择多个视频'}</span>
        <span className="mt-2 block text-xs">主进程会重新校验格式、路径与文件类型；一次最多 100 个</span>
      </button>

      <div className="mt-5 space-y-3" aria-label="待处理视频队列">
        {queue.length === 0 && (
          <div className="rounded-2xl border border-white/5 bg-slate-950/30 px-5 py-8 text-center text-sm text-slate-500">
            队列为空。可一次加入整季视频，确认质量配置后再启动顺序处理。
          </div>
        )}
        {queue.map((video, index) => (
          <article key={video.id} className="rounded-2xl border border-white/10 bg-slate-950/65 p-4">
            <div className="flex items-start gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-cyan-400/10 font-mono text-xs text-cyan-300">
                {String(index + 1).padStart(2, '0')}
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-sm font-medium text-slate-100">{video.name}</h3>
                {statuses[video.path] && <span className="mt-1 inline-block rounded-full bg-white/5 px-2 py-0.5 text-[10px] uppercase text-slate-400">{statuses[video.path]}</span>}
                <p className="mt-1 truncate font-mono text-xs text-slate-500">{video.path}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span>{formatFileSize(video.size)}</span>
                  <span>·</span>
                  <button type="button" disabled={locked} onClick={() => onAttachSubtitle(video.id)} className="text-cyan-300 hover:text-cyan-200 disabled:opacity-30">
                    {video.japaneseSubtitlePath ? '更换日文字幕' : '关联日文字幕'}
                  </button>
                  {video.japaneseSubtitlePath && (
                    <span className="max-w-64 truncate text-emerald-300" title={video.japaneseSubtitlePath}>
                      {video.japaneseSubtitlePath}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 gap-1">
                <button aria-label={`上移 ${video.name}`} disabled={locked || index === 0} onClick={() => onMove(video.id, -1)} className="rounded-lg px-2 py-1 text-slate-400 hover:bg-white/5 disabled:opacity-20">↑</button>
                <button aria-label={`下移 ${video.name}`} disabled={locked || index === queue.length - 1} onClick={() => onMove(video.id, 1)} className="rounded-lg px-2 py-1 text-slate-400 hover:bg-white/5 disabled:opacity-20">↓</button>
                <button aria-label={`移除 ${video.name}`} disabled={locked} onClick={() => onRemove(video.id)} className="rounded-lg px-2 py-1 text-slate-400 hover:bg-rose-400/10 hover:text-rose-300 disabled:opacity-20">×</button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
