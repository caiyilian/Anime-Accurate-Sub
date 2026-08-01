import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import type {
  CommandPreview,
  PipelineEvent,
  PipelineJob,
  PipelineLogLine,
  PipelineSnapshot,
  PipelineSettings,
  VideoInput
} from '../shared/types'
import {
  completeProgress,
  createInitialProgress,
  failProgress,
  mergeProgress,
  readProgressFromFiles,
  sanitizeLogLine,
  updateProgressFromLine
} from './progress'

export interface PipelineSnapshotStore {
  load(): PipelineSnapshot | null
  save(snapshot: PipelineSnapshot | null): void
}

export interface PipelineJobInput {
  video: VideoInput
  japaneseSubtitlePath: string
  settings: PipelineSettings
}

export interface PipelineManagerOptions {
  store: PipelineSnapshotStore
  commandFactory: (job: PipelineJob) => Promise<CommandPreview>
  emit?: (event: PipelineEvent) => void
  spawnProcess?: typeof spawn
  terminateProcess?: (child: ChildProcessWithoutNullStreams) => Promise<void>
  now?: () => Date
  idFactory?: () => string
  maxLogLines?: number
  maxLogEventsPerSecond?: number
  progressReader?: (job: PipelineJob) => Promise<PipelineJob['progress']>
}

function cloneSnapshot(snapshot: PipelineSnapshot | null): PipelineSnapshot | null {
  return snapshot ? structuredClone(snapshot) : null
}

export async function terminateProcessTree(child: ChildProcessWithoutNullStreams): Promise<void> {
  if (!child.pid || child.exitCode !== null) return
  if (process.platform === 'win32') {
    await new Promise<void>((resolve) => {
      const killer = spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], {
        shell: false,
        windowsHide: true,
        stdio: 'ignore'
      })
      killer.once('error', () => {
        child.kill()
        resolve()
      })
      killer.once('close', () => resolve())
    })
    return
  }
  child.kill('SIGTERM')
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      if (child.exitCode === null) child.kill('SIGKILL')
      resolve()
    }, 3_000)
    child.once('close', () => {
      clearTimeout(timer)
      resolve()
    })
  })
}

export class PipelineManager {
  private snapshot: PipelineSnapshot | null
  private child: ChildProcessWithoutNullStreams | null = null
  private cancelRequested = false
  private shuttingDown = false
  private readonly idleWaiters = new Set<() => void>()
  private readonly spawnProcess: typeof spawn
  private readonly terminateProcess: (child: ChildProcessWithoutNullStreams) => Promise<void>
  private readonly now: () => Date
  private readonly idFactory: () => string
  private readonly maxLogLines: number
  private readonly maxLogEventsPerSecond: number
  private readonly progressReader: (job: PipelineJob) => Promise<PipelineJob['progress']>
  private progressTimer: NodeJS.Timeout | undefined
  private logsSincePersist = 0
  private logWindowStartedAt = 0
  private logEventsInWindow = 0
  private droppedLogEvents = 0

  constructor(private readonly options: PipelineManagerOptions) {
    this.spawnProcess = options.spawnProcess ?? spawn
    this.terminateProcess = options.terminateProcess ?? terminateProcessTree
    this.now = options.now ?? (() => new Date())
    this.idFactory = options.idFactory ?? randomUUID
    this.maxLogLines = options.maxLogLines ?? 500
    this.maxLogEventsPerSecond = options.maxLogEventsPerSecond ?? 200
    this.progressReader = options.progressReader ?? readProgressFromFiles
    this.snapshot = this.recover(options.store.load())
    if (this.snapshot) this.persistAndEmit()
  }

  private timestamp(): string {
    return this.now().toISOString()
  }

  private recover(snapshot: PipelineSnapshot | null): PipelineSnapshot | null {
    if (!snapshot) return null
    const recovered = cloneSnapshot(snapshot)!
    let interrupted = recovered.status === 'running' || recovered.status === 'canceling'
    for (const job of recovered.jobs) {
      job.progress ??= createInitialProgress(
        job.settings,
        Boolean(job.japaneseSubtitlePath),
        this.timestamp()
      )
      if (job.status === 'succeeded')
        job.progress = completeProgress(job.progress, this.timestamp())
      if (job.status === 'running') {
        job.status = 'interrupted'
        job.finishedAt = this.timestamp()
        job.error = '桌面应用在任务运行期间退出；可从 Python checkpoint 继续'
        interrupted = true
      }
    }
    recovered.overallPercent = this.calculateOverall(recovered)
    if (interrupted) {
      recovered.status = 'interrupted'
      recovered.currentJobId = undefined
      recovered.finishedAt = this.timestamp()
      recovered.updatedAt = this.timestamp()
    }
    return recovered
  }

  getSnapshot(): PipelineSnapshot | null {
    return cloneSnapshot(this.snapshot)
  }

  private isActive(): boolean {
    return this.snapshot?.status === 'running' || this.snapshot?.status === 'canceling'
  }

  private persistAndEmit(): void {
    if (this.snapshot) {
      this.snapshot.updatedAt = this.timestamp()
      this.snapshot.overallPercent = this.calculateOverall(this.snapshot)
    }
    this.options.store.save(cloneSnapshot(this.snapshot))
    this.logsSincePersist = 0
    this.options.emit?.({ type: 'snapshot', snapshot: cloneSnapshot(this.snapshot) })
  }

  private calculateOverall(snapshot: PipelineSnapshot): number {
    if (!snapshot.jobs.length) return 0
    const total = snapshot.jobs.reduce(
      (sum, job) => sum + (job.status === 'succeeded' ? 100 : (job.progress?.overallPercent ?? 0)),
      0
    )
    return Math.round((total / snapshot.jobs.length) * 10) / 10
  }

  private appendLog(log: PipelineLogLine): void {
    if (!this.snapshot) return
    this.snapshot.logs.push(log)
    if (this.snapshot.logs.length > this.maxLogLines) {
      this.snapshot.logs.splice(0, this.snapshot.logs.length - this.maxLogLines)
    }
    this.options.emit?.({ type: 'log', runId: this.snapshot.runId, log: structuredClone(log) })
    this.logsSincePersist += 1
    if (this.logsSincePersist >= 20) {
      this.options.store.save(cloneSnapshot(this.snapshot))
      this.logsSincePersist = 0
    }
  }

  private flushDroppedLogSummary(jobId: string): void {
    if (!this.droppedLogEvents) return
    this.appendLog({
      at: this.timestamp(),
      jobId,
      stream: 'system',
      line: `有 ${this.droppedLogEvents} 行高频日志被限流`
    })
    this.droppedLogEvents = 0
  }

  private addLog(jobId: string, stream: PipelineLogLine['stream'], line: string): void {
    if (!this.snapshot || !line.trim()) return
    const now = this.now()
    const sanitized = sanitizeLogLine(line.trimEnd())
    if (stream === 'system') {
      this.appendLog({ at: now.toISOString(), jobId, stream, line: sanitized })
      return
    }
    if (!this.logWindowStartedAt || now.getTime() - this.logWindowStartedAt >= 1_000) {
      if (this.droppedLogEvents > 0) {
        this.appendLog({
          at: now.toISOString(),
          jobId,
          stream: 'system',
          line: `上一秒有 ${this.droppedLogEvents} 行高频日志被限流`
        })
      }
      this.logWindowStartedAt = now.getTime()
      this.logEventsInWindow = 0
      this.droppedLogEvents = 0
    }
    if (this.logEventsInWindow >= this.maxLogEventsPerSecond) {
      this.droppedLogEvents += 1
      return
    }
    this.logEventsInWindow += 1
    const log: PipelineLogLine = { at: now.toISOString(), jobId, stream, line: sanitized }
    this.appendLog(log)
    const job = this.snapshot.jobs.find((candidate) => candidate.id === jobId)
    if (job) {
      const next = updateProgressFromLine(job.progress, sanitized, job.settings, log.at)
      if (next !== job.progress) {
        job.progress = next
        this.persistAndEmit()
      }
    }
  }

  private attachLineReader(
    stream: NodeJS.ReadableStream,
    jobId: string,
    kind: PipelineLogLine['stream']
  ): void {
    let buffer = ''
    stream.on('data', (chunk) => {
      buffer += String(chunk)
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() ?? ''
      for (const line of lines) this.addLog(jobId, kind, line)
    })
    stream.once('end', () => {
      if (buffer) this.addLog(jobId, kind, buffer)
    })
  }

  async start(inputs: PipelineJobInput[], continueOnError: boolean): Promise<PipelineSnapshot> {
    if (this.isActive()) throw new Error('已有管线正在运行')
    if (!inputs.length) throw new TypeError('至少需要一个视频任务')
    const createdAt = this.timestamp()
    this.cancelRequested = false
    this.shuttingDown = false
    this.snapshot = {
      schemaVersion: 1,
      runId: this.idFactory(),
      status: 'running',
      continueOnError,
      createdAt,
      updatedAt: createdAt,
      startedAt: createdAt,
      overallPercent: 0,
      jobs: inputs.map((input) => ({
        id: this.idFactory(),
        video: structuredClone(input.video),
        japaneseSubtitlePath: input.japaneseSubtitlePath,
        settings: structuredClone(input.settings),
        status: 'pending',
        progress: createInitialProgress(
          input.settings,
          Boolean(input.japaneseSubtitlePath),
          createdAt
        )
      })),
      logs: []
    }
    this.persistAndEmit()
    void this.runNext()
    return this.getSnapshot()!
  }

  async resume(): Promise<PipelineSnapshot> {
    if (this.isActive()) throw new Error('已有管线正在运行')
    if (!this.snapshot) throw new Error('没有可恢复的管线')
    const unfinished = this.snapshot.jobs.filter((job) => job.status !== 'succeeded')
    if (!unfinished.length) throw new Error('所有任务已经完成')
    for (const job of unfinished) {
      job.status = 'pending'
      job.startedAt = undefined
      job.finishedAt = undefined
      job.exitCode = undefined
      job.error = undefined
    }
    this.snapshot.status = 'running'
    this.snapshot.startedAt = this.timestamp()
    this.snapshot.finishedAt = undefined
    this.snapshot.currentJobId = undefined
    this.cancelRequested = false
    this.shuttingDown = false
    this.persistAndEmit()
    void this.runNext()
    return this.getSnapshot()!
  }

  async cancel(): Promise<PipelineSnapshot | null> {
    if (!this.snapshot || !this.isActive()) return this.getSnapshot()
    this.cancelRequested = true
    this.snapshot.status = 'canceling'
    this.persistAndEmit()
    if (this.child) await this.terminateProcess(this.child)
    else this.finishCanceled()
    return this.getSnapshot()
  }

  async shutdown(): Promise<void> {
    if (!this.snapshot || !this.isActive()) return
    this.shuttingDown = true
    this.stopProgressPolling()
    const current = this.snapshot.jobs.find((job) => job.id === this.snapshot?.currentJobId)
    if (current) {
      current.status = 'interrupted'
      current.finishedAt = this.timestamp()
      current.error = '桌面应用退出；重新打开后可继续'
    }
    this.snapshot.status = 'interrupted'
    this.snapshot.currentJobId = undefined
    this.snapshot.finishedAt = this.timestamp()
    this.persistAndEmit()
    if (this.child) await this.terminateProcess(this.child)
    this.resolveIdleWaiters()
  }

  waitForIdle(): Promise<void> {
    if (!this.isActive()) return Promise.resolve()
    return new Promise((resolve) => this.idleWaiters.add(resolve))
  }

  private resolveIdleWaiters(): void {
    for (const resolve of this.idleWaiters) resolve()
    this.idleWaiters.clear()
  }

  private finishCanceled(): void {
    if (!this.snapshot) return
    this.snapshot.status = 'canceled'
    this.snapshot.currentJobId = undefined
    this.snapshot.finishedAt = this.timestamp()
    this.stopProgressPolling()
    this.persistAndEmit()
    this.resolveIdleWaiters()
  }

  private finishRun(): void {
    if (!this.snapshot) return
    this.snapshot.status = this.snapshot.jobs.some((job) => job.status === 'failed')
      ? 'failed'
      : 'completed'
    this.snapshot.currentJobId = undefined
    this.snapshot.finishedAt = this.timestamp()
    this.stopProgressPolling()
    this.persistAndEmit()
    this.resolveIdleWaiters()
  }

  private async failBeforeSpawn(job: PipelineJob, error: unknown): Promise<void> {
    if (!this.snapshot) return
    job.status = 'failed'
    job.finishedAt = this.timestamp()
    job.error = error instanceof Error ? error.message : String(error)
    job.progress = failProgress(job.progress, this.timestamp())
    this.addLog(job.id, 'system', `任务准备失败：${job.error}`)
    this.snapshot.currentJobId = undefined
    this.persistAndEmit()
    if (this.snapshot.continueOnError) await this.runNext()
    else this.finishRun()
  }

  private stopProgressPolling(): void {
    if (this.progressTimer) clearInterval(this.progressTimer)
    this.progressTimer = undefined
  }

  private async refreshProgress(job: PipelineJob): Promise<void> {
    if (!this.snapshot || job.status !== 'running') return
    try {
      const incoming = await this.progressReader(structuredClone(job))
      const merged = mergeProgress(job.progress, incoming)
      if (JSON.stringify(merged) !== JSON.stringify(job.progress)) {
        job.progress = merged
        this.persistAndEmit()
      }
    } catch (error) {
      this.addLog(
        job.id,
        'system',
        `进度文件读取失败：${error instanceof Error ? error.message : String(error)}`
      )
    }
  }

  private startProgressPolling(job: PipelineJob): void {
    this.stopProgressPolling()
    void this.refreshProgress(job)
    this.progressTimer = setInterval(() => void this.refreshProgress(job), 1_000)
  }

  private async runNext(): Promise<void> {
    if (!this.snapshot || this.cancelRequested || this.shuttingDown) return
    const job = this.snapshot.jobs.find((candidate) => candidate.status === 'pending')
    if (!job) {
      this.finishRun()
      return
    }
    job.status = 'running'
    job.startedAt = this.timestamp()
    this.snapshot.currentJobId = job.id
    this.persistAndEmit()

    let command: CommandPreview
    try {
      command = await this.options.commandFactory(job)
      job.command = structuredClone(command)
      this.persistAndEmit()
    } catch (error) {
      await this.failBeforeSpawn(job, error)
      return
    }

    let child: ChildProcessWithoutNullStreams
    try {
      child = this.spawnProcess(command.executable, command.args, {
        cwd: command.cwd,
        env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
        shell: false,
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe']
      }) as ChildProcessWithoutNullStreams
    } catch (error) {
      await this.failBeforeSpawn(job, error)
      return
    }
    this.child = child
    this.logWindowStartedAt = this.now().getTime()
    this.logEventsInWindow = 0
    this.droppedLogEvents = 0
    this.startProgressPolling(job)
    this.addLog(job.id, 'system', `启动：${command.display}`)
    this.attachLineReader(child.stdout, job.id, 'stdout')
    this.attachLineReader(child.stderr, job.id, 'stderr')
    let settled = false
    const settle = async (code: number | null, error?: Error): Promise<void> => {
      if (settled || !this.snapshot) return
      settled = true
      this.stopProgressPolling()
      this.flushDroppedLogSummary(job.id)
      this.child = null
      job.finishedAt = this.timestamp()
      job.exitCode = code
      if (this.shuttingDown) {
        job.status = 'interrupted'
        job.error = job.error ?? '桌面应用退出'
        return
      }
      if (this.cancelRequested) {
        job.status = 'canceled'
        job.error = '用户取消'
        this.finishCanceled()
        return
      }
      if (error || code !== 0) {
        job.status = 'failed'
        job.error = error?.message ?? `Python 退出码 ${code}`
        job.progress = failProgress(job.progress, this.timestamp())
        this.addLog(job.id, 'system', `任务失败：${job.error}`)
      } else {
        job.status = 'succeeded'
        job.progress = completeProgress(job.progress, this.timestamp())
        this.addLog(job.id, 'system', '任务完成')
      }
      this.snapshot.currentJobId = undefined
      this.persistAndEmit()
      if (job.status === 'failed' && !this.snapshot.continueOnError) this.finishRun()
      else await this.runNext()
    }
    child.once('error', (error) => void settle(null, error))
    child.once('close', (code) => void settle(code))
  }
}
