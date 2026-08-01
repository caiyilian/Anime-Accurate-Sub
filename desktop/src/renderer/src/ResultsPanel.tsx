import { useState } from 'react'
import type {
  DesktopApi,
  ResultArtifact,
  ResultBundle,
  TextArtifactContent
} from '../../shared/types'
import { formatFileSize } from './queue'

export default function ResultsPanel({
  bundles,
  api,
  onRefresh
}: {
  bundles: ResultBundle[]
  api: Readonly<DesktopApi>
  onRefresh: () => void
}): React.JSX.Element {
  const [preview, setPreview] = useState<TextArtifactContent | null>(null)
  const [error, setError] = useState('')

  const readArtifact = async (artifact: ResultArtifact): Promise<void> => {
    setError('')
    try {
      setPreview(await api.readResultArtifact(artifact.id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  const exportLog = async (): Promise<void> => {
    const path = await api.exportPipelineLog()
    if (path) setError(`日志已导出：${path}`)
  }

  return (
    <section className="mt-6 rounded-3xl border border-white/10 bg-slate-900/45 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
            06 / 成品与阶段产物
          </p>
          <h2 className="mt-2 text-lg font-semibold">字幕、嵌字视频与质量报告</h2>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300"
          >
            刷新结果
          </button>
          <button
            type="button"
            onClick={() => void exportLog()}
            className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300"
          >
            导出运行日志
          </button>
        </div>
      </div>

      {bundles.length === 0 && (
        <div className="mt-4 rounded-2xl border border-dashed border-white/10 px-5 py-8 text-center text-sm text-slate-500">
          暂无结果。任务产生 checkpoint、字幕或视频后，可在这里刷新查看。
        </div>
      )}

      <div className="mt-5 grid gap-4 xl:grid-cols-2">
        {bundles.map((bundle) => {
          const video = bundle.artifacts.find((artifact) => artifact.kind === 'video')
          return (
            <article
              key={bundle.jobId}
              className="min-w-0 rounded-2xl border border-white/8 bg-slate-950/45 p-4"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-medium">{bundle.videoName}</h3>
                  <p className="mt-1 text-xs uppercase text-slate-500">{bundle.jobStatus}</p>
                </div>
                <button
                  type="button"
                  onClick={() => void api.openResultDirectory(bundle.jobId)}
                  className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-cyan-300"
                >
                  打开目录
                </button>
              </div>
              {video?.mediaUrl && (
                <video
                  controls
                  preload="metadata"
                  src={video.mediaUrl}
                  className="mt-4 aspect-video w-full rounded-xl bg-black"
                  aria-label={`${bundle.videoName} 嵌字视频`}
                />
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                {bundle.artifacts.map((artifact) =>
                  artifact.kind === 'video' ? (
                    <span
                      key={artifact.id}
                      className="rounded-lg bg-emerald-400/8 px-3 py-2 text-xs text-emerald-300"
                    >
                      {artifact.label} · {formatFileSize(artifact.size)}
                    </span>
                  ) : (
                    <button
                      key={artifact.id}
                      type="button"
                      onClick={() => void readArtifact(artifact)}
                      className="rounded-lg border border-white/10 px-3 py-2 text-left text-xs text-slate-300 hover:border-cyan-400/30"
                    >
                      {artifact.label} · {formatFileSize(artifact.size)}
                    </button>
                  )
                )}
                {bundle.artifacts.length === 0 && (
                  <span className="text-xs text-slate-600">工作目录已登记，尚无可预览文件。</span>
                )}
              </div>
            </article>
          )
        })}
      </div>

      {(preview || error) && (
        <div className="mt-5 rounded-2xl border border-white/8 bg-[#050810] p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">{preview?.name ?? '结果操作'}</h3>
            <button
              type="button"
              onClick={() => {
                setPreview(null)
                setError('')
              }}
              className="text-xs text-slate-500"
            >
              关闭
            </button>
          </div>
          {error && (
            <p role="status" className="mt-3 break-all text-sm text-amber-300">
              {error}
            </p>
          )}
          {preview && (
            <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-xs leading-5 text-slate-400">
              {preview.content}
            </pre>
          )}
        </div>
      )}
    </section>
  )
}
