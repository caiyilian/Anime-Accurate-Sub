// @vitest-environment node
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { DEFAULT_SETTINGS, sanitizeSettings } from './settings'

describe('sanitizeSettings', () => {
  it('normalizes absolute paths and preserves quality-first defaults', () => {
    const settings = sanitizeSettings({
      ...DEFAULT_SETTINGS,
      outputRoot: resolve('output', 'desktop-test')
    })
    expect(settings.outputRoot).toBe(resolve('output', 'desktop-test'))
    expect(settings.multiAgentReview).toBe(true)
    expect(settings.mqmQualityReview).toBe(true)
  })

  it('rejects unknown fields, relative paths and invalid ranges', () => {
    expect(() => sanitizeSettings({ ...DEFAULT_SETTINGS, secretToken: 'never' })).toThrow(
      '未知设置字段'
    )
    expect(() => sanitizeSettings({ ...DEFAULT_SETTINGS, projectRoot: '..\\repo' })).toThrow(
      '必须是绝对路径'
    )
    expect(() => sanitizeSettings({ ...DEFAULT_SETTINGS, translationContextWindow: 999 })).toThrow(
      '0-50'
    )
  })
})
