import { createHash } from 'node:crypto'
import { lstat, readFile } from 'node:fs/promises'
import { isAbsolute, join, parse, relative, resolve } from 'node:path'
import type {
  PipelineSnapshot,
  ResultArtifact,
  ResultArtifactKind,
  ResultBundle,
  TextArtifactContent
} from '../shared/types'

const MAX_TEXT_ARTIFACT_BYTES = 2 * 1024 * 1024

interface RegisteredArtifact extends ResultArtifact {
  path: string
}

interface ArtifactSpec {
  kind: ResultArtifactKind
  label: string
  file: (stem: string) => string
  text: boolean
}

const ARTIFACT_SPECS: ArtifactSpec[] = [
  { kind: 'subtitle-srt', label: 'SRT 字幕', file: (stem) => `${stem}.srt`, text: true },
  { kind: 'subtitle-ass', label: 'ASS 字幕', file: (stem) => `${stem}.ass`, text: true },
  { kind: 'video', label: '嵌字视频', file: (stem) => `${stem}_subs.mp4`, text: false },
  { kind: 'quality-report', label: '质量报告', file: () => 'quality_report.json', text: true },
  { kind: 'multi-agent-report', label: '多 Agent 报告', file: () => 'multi_agent_review.json', text: true },
  { kind: 'mqm-report', label: 'MQM 报告', file: () => 'mqm_quality_report.json', text: true },
  { kind: 'checkpoint', label: '断点状态', file: () => 'checkpoint.json', text: true },
  { kind: 'translated', label: '翻译结果', file: () => 'translated.json', text: true },
  { kind: 'reviewed', label: '多 Agent 修订', file: () => 'reviewed.json', text: true },
  { kind: 'mqm-reviewed', label: 'MQM 修订', file: () => 'mqm_reviewed.json', text: true }
]

function isWithin(root: string, candidate: string): boolean {
  const path = relative(root, candidate)
  return path === '' || (!path.startsWith('..') && !isAbsolute(path))
}

function outputRoot(snapshotJob: PipelineSnapshot['jobs'][number]): string {
  const index = snapshotJob.command?.args.indexOf('--output-dir') ?? -1
  return index >= 0 ? snapshotJob.command!.args[index + 1] : snapshotJob.settings.outputRoot
}

export function formatPipelineLog(snapshot: PipelineSnapshot): string {
  const names = new Map(snapshot.jobs.map((job) => [job.id, job.video.name]))
  const lines = [
    'Anime Accurate Sub Desktop Pipeline Log',
    `Run: ${snapshot.runId}`,
    `Status: ${snapshot.status}`,
    `Created: ${snapshot.createdAt}`,
    ''
  ]
  for (const log of snapshot.logs) {
    lines.push(`${log.at} [${names.get(log.jobId) ?? log.jobId}] [${log.stream}] ${log.line}`)
  }
  return `${lines.join('\n')}\n`
}

export class ResultRegistry {
  private artifacts = new Map<string, RegisteredArtifact>()
  private directories = new Map<string, string>()

  async refresh(snapshot: PipelineSnapshot | null): Promise<ResultBundle[]> {
    this.artifacts.clear()
    this.directories.clear()
    if (!snapshot) return []
    const bundles: ResultBundle[] = []
    for (const job of snapshot.jobs) {
      const configuredRoot = outputRoot(job)
      if (!configuredRoot || !isAbsolute(configuredRoot)) continue
      const root = resolve(configuredRoot)
      const stem = parse(job.video.name).name
      const workDir = resolve(root, stem)
      if (!isWithin(root, workDir)) continue
      const artifacts: ResultArtifact[] = []
      for (const spec of ARTIFACT_SPECS) {
        const path = join(workDir, spec.file(stem))
        if (!isWithin(root, path)) continue
        try {
          const info = await lstat(path)
          if (!info.isFile()) continue
          const id = createHash('sha256').update(`${job.id}\0${spec.kind}\0${path}`).digest('hex').slice(0, 32)
          const artifact: RegisteredArtifact = {
            id,
            kind: spec.kind,
            label: spec.label,
            name: parse(path).base,
            size: info.size,
            modifiedAt: info.mtime.toISOString(),
            mediaUrl: spec.kind === 'video' ? `aas-media://artifact/${id}` : undefined,
            path
          }
          this.artifacts.set(id, artifact)
          const { path: _path, ...publicArtifact } = artifact
          artifacts.push(publicArtifact)
        } catch {
          // Partial and failed jobs legitimately omit later artifacts.
        }
      }
      this.directories.set(job.id, workDir)
      bundles.push({ jobId: job.id, videoName: job.video.name, jobStatus: job.status, artifacts })
    }
    return bundles
  }

  async readText(id: string): Promise<TextArtifactContent> {
    const artifact = this.artifacts.get(id)
    if (!artifact || artifact.kind === 'video') throw new Error('未知或不可读取的文本 artifact')
    const info = await lstat(artifact.path)
    if (!info.isFile() || info.size > MAX_TEXT_ARTIFACT_BYTES) {
      throw new Error(`文本 artifact 超过 ${MAX_TEXT_ARTIFACT_BYTES} 字节限制`)
    }
    const bytes = await readFile(artifact.path)
    let content: string
    try {
      content = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    } catch {
      throw new Error('文本 artifact 不是有效 UTF-8')
    }
    return { id: artifact.id, name: artifact.name, content }
  }

  getVideoPath(id: string): string {
    const artifact = this.artifacts.get(id)
    if (!artifact || artifact.kind !== 'video') throw new Error('未知视频 artifact')
    return artifact.path
  }

  getDirectory(jobId: string): string {
    const path = this.directories.get(jobId)
    if (!path) throw new Error('未知结果目录')
    return path
  }
}
