// @vitest-environment node
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { CommandPreview, PipelineJob, PipelineSnapshot, VideoInput } from '../shared/types'
import { PipelineManager, type PipelineJobInput, type PipelineSnapshotStore } from './pipeline-manager'
import { DEFAULT_SETTINGS } from './settings'

class MemoryStore implements PipelineSnapshotStore {
  constructor(public value: PipelineSnapshot | null = null) {}
  load(): PipelineSnapshot | null {
    return this.value ? structuredClone(this.value) : null
  }
  save(snapshot: PipelineSnapshot | null): void {
    this.value = snapshot ? structuredClone(snapshot) : null
  }
}

const video = (name: string): VideoInput => ({
  id: name,
  path: resolve(name),
  name,
  size: 1,
  modifiedAt: '2026-07-29T00:00:00.000Z'
})

const input = (name: string): PipelineJobInput => ({
  video: video(name),
  japaneseSubtitlePath: '',
  settings: { ...DEFAULT_SETTINGS }
})

function nodeCommand(job: PipelineJob, delay = 25): Promise<CommandPreview> {
  const shouldFail = job.video.name.includes('fail')
  const script = `console.log('start:${job.video.name}');setTimeout(()=>{console.log('end:${job.video.name}');process.exit(${shouldFail ? 2 : 0})},${delay})`
  return Promise.resolve({
    executable: process.execPath,
    args: ['-e', script],
    cwd: process.cwd(),
    display: `node worker ${job.video.name}`
  })
}

describe('PipelineManager', () => {
  it('runs jobs strictly in sequence and retains bounded line logs', async () => {
    const manager = new PipelineManager({ store: new MemoryStore(), commandFactory: nodeCommand, maxLogLines: 20 })
    await manager.start([input('01.mp4'), input('02.mp4')], true)
    await manager.waitForIdle()

    const snapshot = manager.getSnapshot()!
    expect(snapshot.status).toBe('completed')
    expect(snapshot.jobs.map((job) => job.status)).toEqual(['succeeded', 'succeeded'])
    expect(snapshot.logs.filter((line) => line.stream === 'stdout').map((line) => line.line)).toEqual([
      'start:01.mp4',
      'end:01.mp4',
      'start:02.mp4',
      'end:02.mp4'
    ])
  })

  it('continues after a failure when configured and rejects a concurrent start', async () => {
    const manager = new PipelineManager({ store: new MemoryStore(), commandFactory: nodeCommand })
    await manager.start([input('fail.mp4'), input('ok.mp4')], true)
    await expect(manager.start([input('other.mp4')], true)).rejects.toThrow('已有管线')
    await manager.waitForIdle()

    expect(manager.getSnapshot()!.status).toBe('failed')
    expect(manager.getSnapshot()!.jobs.map((job) => job.status)).toEqual(['failed', 'succeeded'])
  })

  it('stops before later pending jobs when continueOnError is disabled', async () => {
    const manager = new PipelineManager({ store: new MemoryStore(), commandFactory: nodeCommand })
    await manager.start([input('fail.mp4'), input('never-started.mp4')], false)
    await manager.waitForIdle()

    expect(manager.getSnapshot()!.status).toBe('failed')
    expect(manager.getSnapshot()!.jobs.map((job) => job.status)).toEqual(['failed', 'pending'])
    expect(manager.getSnapshot()!.logs.some((line) => line.line.includes('start:never-started'))).toBe(false)
  })

  it('cancels the active child and preserves unfinished jobs for resume', async () => {
    const manager = new PipelineManager({
      store: new MemoryStore(),
      commandFactory: (job) => nodeCommand(job, 10_000),
      terminateProcess: async (child) => {
        child.kill()
      }
    })
    await manager.start([input('long.mp4'), input('later.mp4')], true)
    await new Promise((resolve) => setTimeout(resolve, 80))
    await manager.cancel()
    await manager.waitForIdle()
    const canceled = manager.getSnapshot()!
    expect(canceled.status).toBe('canceled')
    expect(canceled.jobs.map((job) => job.status)).toEqual(['canceled', 'pending'])

    await manager.resume()
    await new Promise((resolve) => setTimeout(resolve, 80))
    await manager.cancel()
    await manager.waitForIdle()
    expect(manager.getSnapshot()!.jobs[0].status).toBe('canceled')
  })

  it('marks an orphaned running job interrupted and skips succeeded jobs on resume', async () => {
    const settings = { ...DEFAULT_SETTINGS }
    const stored = new MemoryStore({
      schemaVersion: 1,
      runId: 'old-run',
      status: 'running',
      continueOnError: true,
      createdAt: '2026-07-29T00:00:00.000Z',
      updatedAt: '2026-07-29T00:00:00.000Z',
      currentJobId: 'job-2',
      jobs: [
        { id: 'job-1', video: video('done.mp4'), japaneseSubtitlePath: '', settings, status: 'succeeded' },
        { id: 'job-2', video: video('resume.mp4'), japaneseSubtitlePath: '', settings, status: 'running' }
      ],
      logs: []
    })
    let commands = 0
    const manager = new PipelineManager({
      store: stored,
      commandFactory: (job) => {
        commands += 1
        return nodeCommand(job)
      }
    })
    expect(manager.getSnapshot()!.status).toBe('interrupted')
    expect(manager.getSnapshot()!.jobs[1].status).toBe('interrupted')

    await manager.resume()
    await manager.waitForIdle()
    expect(commands).toBe(1)
    expect(manager.getSnapshot()!.jobs.map((job) => job.status)).toEqual(['succeeded', 'succeeded'])
  })
})
