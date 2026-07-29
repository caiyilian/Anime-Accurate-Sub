// @vitest-environment node
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { DiagnosticsResult } from '../shared/types'
import { buildPipelineCommand } from './command'
import { DEFAULT_SETTINGS } from './settings'

const root = resolve('project')
const diagnostics: DiagnosticsResult = {
  ready: true,
  checkedAt: '2026-07-29T00:00:00.000Z',
  checks: [],
  resolved: {
    projectRoot: root,
    pythonPath: resolve('python.exe'),
    outputRoot: resolve('output', 'desktop-test'),
    ffmpegPath: 'ffmpeg'
  },
  logPath: ''
}

describe('buildPipelineCommand', () => {
  it('builds a shell-free quality-first argument vector', () => {
    const preview = buildPipelineCommand(
      { videoPath: resolve('data', 'episode 01.mp4') },
      { ...DEFAULT_SETTINGS },
      diagnostics,
      false
    )
    expect(preview.executable).toBe(diagnostics.resolved.pythonPath)
    expect(preview.args).toContain('--multi-agent-review')
    expect(preview.args).toContain('--mqm-quality-review')
    expect(preview.args).toContain('--prefer-japanese-subtitles')
    expect(preview.display).not.toMatch(/token|api[_-]?key/i)
    expect(preview).not.toHaveProperty('shell')
  })

  it('rejects relative video paths before command construction', () => {
    expect(() =>
      buildPipelineCommand({ videoPath: 'episode.mp4' }, { ...DEFAULT_SETTINGS }, diagnostics, false)
    ).toThrow('绝对路径')
  })
})
