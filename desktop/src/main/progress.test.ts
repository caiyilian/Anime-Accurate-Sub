// @vitest-environment node
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { PipelineJob } from '../shared/types'
import { DEFAULT_SETTINGS } from './settings'
import {
  completeProgress,
  createInitialProgress,
  readProgressFromFiles,
  sanitizeLogLine,
  updateProgressFromLine
} from './progress'

let temporary = ''
afterEach(async () => {
  if (temporary) await rm(temporary, { recursive: true, force: true })
  temporary = ''
})

describe('pipeline progress', () => {
  it('parses real stage and ratio lines without regressing on stale lines', () => {
    const settings = { ...DEFAULT_SETTINGS }
    let progress = createInitialProgress(settings, false, '2026-07-29T00:00:00.000Z')
    progress = updateProgressFromLine(progress, '[translate]', settings)
    progress = updateProgressFromLine(progress, '  Translated: 30/100', settings)
    expect(progress.activeStage).toBe('translate')
    expect(progress.stagePercent).toBe(30)
    const current = progress.overallPercent
    progress = updateProgressFromLine(progress, '[asr]', settings)
    expect(progress.activeStage).toBe('translate')
    expect(progress.overallPercent).toBe(current)
    expect(updateProgressFromLine(progress, 'ordinary log text', settings)).toBe(progress)
  })

  it('switches to the Japanese subtitle plan and clamps percentages', () => {
    const settings = { ...DEFAULT_SETTINGS }
    let progress = createInitialProgress(settings, false)
    progress = updateProgressFromLine(progress, '[japanese_subtitle]', settings)
    progress = updateProgressFromLine(progress, '  [999/100] ok', settings)
    expect(progress.stages.some((stage) => stage.key === 'japanese_subtitle')).toBe(true)
    expect(progress.stages.some((stage) => stage.key === 'asr')).toBe(false)
    expect(progress.stagePercent).toBe(100)
    expect(completeProgress(progress).overallPercent).toBe(100)
  })

  it('rebuilds progress from checkpoint and progress files', async () => {
    temporary = await mkdtemp(join(tmpdir(), 'anime-sub-progress-'))
    const workDir = join(temporary, 'episode')
    await mkdir(workDir)
    await writeFile(
      join(workDir, 'checkpoint.json'),
      JSON.stringify({ extract_audio: { status: 'completed' }, asr: { status: 'completed' } })
    )
    await writeFile(
      join(workDir, 'asr_results.json'),
      JSON.stringify(new Array(10).fill({ text: 'ja' }))
    )
    await writeFile(
      join(workDir, 'translated.json'),
      JSON.stringify(new Array(4).fill({ text: 'zh' }))
    )
    const settings = { ...DEFAULT_SETTINGS, outputRoot: temporary }
    const job: PipelineJob = {
      id: 'job',
      video: {
        id: 'video',
        path: resolve('episode.mp4'),
        name: 'episode.mp4',
        size: 1,
        modifiedAt: new Date().toISOString()
      },
      japaneseSubtitlePath: '',
      settings,
      status: 'running',
      progress: createInitialProgress(settings, false)
    }
    const progress = await readProgressFromFiles(job)
    expect(progress.activeStage).toBe('translate')
    expect(progress.stagePercent).toBe(40)
    expect(progress.completedStages).toBeGreaterThanOrEqual(3)
  })

  it('removes terminal escapes and truncates oversized lines', () => {
    const sanitized = sanitizeLogLine(`\u001b[31m${'x'.repeat(30)}\u001b[0m`, 10)
    expect(sanitized).toBe('xxxxxxxxxx…[已截断]')
  })
})
