// @vitest-environment node
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { PipelineSnapshot } from '../shared/types'
import { completeProgress, createInitialProgress } from './progress'
import { formatPipelineLog, ResultRegistry } from './result-registry'
import { DEFAULT_SETTINGS } from './settings'

let temporary = ''
afterEach(async () => {
  if (temporary) await rm(temporary, { recursive: true, force: true })
  temporary = ''
})

function snapshot(outputRoot: string): PipelineSnapshot {
  const settings = { ...DEFAULT_SETTINGS, outputRoot }
  return {
    schemaVersion: 1,
    runId: 'result-run',
    status: 'completed',
    continueOnError: true,
    createdAt: '2026-07-29T00:00:00.000Z',
    updatedAt: '2026-07-29T00:01:00.000Z',
    finishedAt: '2026-07-29T00:01:00.000Z',
    overallPercent: 100,
    jobs: [{
      id: 'job-1',
      video: { id: 'video-1', path: resolve('episode.mp4'), name: 'episode.mp4', size: 1, modifiedAt: '2026-07-29T00:00:00.000Z' },
      japaneseSubtitlePath: '',
      settings,
      status: 'succeeded',
      progress: completeProgress(createInitialProgress(settings, false)),
      command: { executable: 'python', args: ['anime_sub.py', '--output-dir', outputRoot], cwd: resolve('.'), display: 'python anime_sub.py' }
    }],
    logs: [{ at: '2026-07-29T00:00:01.000Z', jobId: 'job-1', stream: 'stdout', line: 'done' }]
  }
}

describe('ResultRegistry', () => {
  it('discovers only known regular artifacts and never exposes paths in media URLs', async () => {
    temporary = await mkdtemp(join(tmpdir(), 'anime-sub-results-'))
    const workDir = join(temporary, 'episode')
    await mkdir(workDir)
    await writeFile(join(workDir, 'episode.srt'), '1\n00:00:00,000 --> 00:00:01,000\n你好\n', 'utf8')
    await writeFile(join(workDir, 'episode_subs.mp4'), 'video')
    await writeFile(join(workDir, 'quality_report.json'), '{"ok":true}', 'utf8')
    await writeFile(join(workDir, 'unregistered-secret.txt'), 'never expose', 'utf8')

    const registry = new ResultRegistry()
    const bundles = await registry.refresh(snapshot(temporary))
    expect(bundles).toHaveLength(1)
    expect(bundles[0].artifacts.map((item) => item.kind)).toEqual(['subtitle-srt', 'video', 'quality-report'])
    const video = bundles[0].artifacts.find((item) => item.kind === 'video')!
    expect(video.mediaUrl).toMatch(/^aas-media:\/\/artifact\/[a-f0-9]{32}$/)
    expect(video.mediaUrl).not.toContain(temporary)
    expect(await registry.readText(bundles[0].artifacts[0].id)).toMatchObject({ content: expect.stringContaining('你好') })
    expect(() => registry.getVideoPath('0'.repeat(32))).toThrow('未知视频')
    await expect(registry.readText('0'.repeat(32))).rejects.toThrow('未知或不可读取')
  })

  it('rejects oversized and invalid UTF-8 text artifacts and formats an exportable log', async () => {
    temporary = await mkdtemp(join(tmpdir(), 'anime-sub-results-'))
    const workDir = join(temporary, 'episode')
    await mkdir(workDir)
    await writeFile(join(workDir, 'translated.json'), Buffer.alloc(2 * 1024 * 1024 + 1, 0x61))
    const registry = new ResultRegistry()
    let bundles = await registry.refresh(snapshot(temporary))
    await expect(registry.readText(bundles[0].artifacts[0].id)).rejects.toThrow('超过')

    await writeFile(join(workDir, 'translated.json'), Buffer.from([0xff, 0xfe, 0xfd]))
    bundles = await registry.refresh(snapshot(temporary))
    await expect(registry.readText(bundles[0].artifacts[0].id)).rejects.toThrow('UTF-8')
    expect(formatPipelineLog(snapshot(temporary))).toContain('[episode.mp4] [stdout] done')
  })
})
