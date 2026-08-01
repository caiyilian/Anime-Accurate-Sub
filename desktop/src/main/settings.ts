import ElectronStore from 'electron-store'
import { isAbsolute, normalize } from 'node:path'
import {
  ASR_BACKENDS,
  SUBTITLE_STYLES,
  TRANSLATION_BACKENDS,
  type PipelineSettings
} from '../shared/types'

const StoreConstructor =
  (ElectronStore as unknown as { default?: typeof ElectronStore }).default ?? ElectronStore

export const DEFAULT_SETTINGS: Readonly<PipelineSettings> = Object.freeze({
  projectRoot: '',
  pythonPath: '',
  outputRoot: '',
  backend: 'sakura',
  asrBackend: 'anime_whisper',
  subtitleStyle: 'anime',
  translationConfigPath: '',
  memoryPath: '',
  glossaryPath: '',
  translationMemoryPath: '',
  japaneseSubtitleDir: '',
  speakerMapPath: '',
  opedSeries: '',
  translationBatchSize: 0,
  translationContextWindow: 3,
  preferJapaneseSubtitles: true,
  qualityCheck: true,
  multiAgentReview: true,
  mqmQualityReview: true,
  autoHardware: false,
  opedBestEffort: true,
  continueOnError: true
})

const PATH_FIELDS = [
  'projectRoot',
  'pythonPath',
  'outputRoot',
  'translationConfigPath',
  'memoryPath',
  'glossaryPath',
  'translationMemoryPath',
  'japaneseSubtitleDir',
  'speakerMapPath'
] as const

const BOOLEAN_FIELDS = [
  'preferJapaneseSubtitles',
  'qualityCheck',
  'multiAgentReview',
  'mqmQualityReview',
  'autoHardware',
  'opedBestEffort',
  'continueOnError'
] as const

const ALLOWED_FIELDS = new Set<keyof PipelineSettings>([
  ...PATH_FIELDS,
  ...BOOLEAN_FIELDS,
  'backend',
  'asrBackend',
  'subtitleStyle',
  'opedSeries',
  'translationBatchSize',
  'translationContextWindow'
])

interface SettingsStore {
  settings: PipelineSettings
}

let store: ElectronStore<SettingsStore> | undefined

function cleanPath(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new TypeError(`${field} 必须是字符串`)
  const trimmed = value.trim()
  if (!trimmed) return ''
  if (trimmed.includes('\0')) throw new TypeError(`${field} 包含非法字符`)
  if (trimmed.length > 4096) throw new RangeError(`${field} 过长`)
  if (!isAbsolute(trimmed)) throw new TypeError(`${field} 必须是绝对路径`)
  return normalize(trimmed)
}

function cleanShortText(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new TypeError(`${field} 必须是字符串`)
  const trimmed = value.trim()
  if (trimmed.includes('\0') || trimmed.length > 200) throw new TypeError(`${field} 无效`)
  return trimmed
}

function cleanInteger(value: unknown, field: string, min: number, max: number): number {
  if (!Number.isInteger(value) || Number(value) < min || Number(value) > max) {
    throw new RangeError(`${field} 必须是 ${min}-${max} 的整数`)
  }
  return Number(value)
}

export function sanitizeSettings(value: unknown): PipelineSettings {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('设置必须是对象')
  }
  const input = value as Record<string, unknown>
  const unknown = Object.keys(input).filter(
    (key) => !ALLOWED_FIELDS.has(key as keyof PipelineSettings)
  )
  if (unknown.length) throw new TypeError(`未知设置字段：${unknown.join(', ')}`)

  const result = { ...DEFAULT_SETTINGS } as PipelineSettings
  for (const field of PATH_FIELDS) result[field] = cleanPath(input[field] ?? result[field], field)
  for (const field of BOOLEAN_FIELDS) {
    const candidate = input[field] ?? result[field]
    if (typeof candidate !== 'boolean') throw new TypeError(`${field} 必须是布尔值`)
    result[field] = candidate
  }

  const backend = input.backend ?? result.backend
  if (!TRANSLATION_BACKENDS.includes(backend as PipelineSettings['backend'])) {
    throw new TypeError('backend 不在允许列表中')
  }
  result.backend = backend as PipelineSettings['backend']

  const asrBackend = input.asrBackend ?? result.asrBackend
  if (!ASR_BACKENDS.includes(asrBackend as PipelineSettings['asrBackend'])) {
    throw new TypeError('asrBackend 不在允许列表中')
  }
  result.asrBackend = asrBackend as PipelineSettings['asrBackend']

  const subtitleStyle = input.subtitleStyle ?? result.subtitleStyle
  if (!SUBTITLE_STYLES.includes(subtitleStyle as PipelineSettings['subtitleStyle'])) {
    throw new TypeError('subtitleStyle 不在允许列表中')
  }
  result.subtitleStyle = subtitleStyle as PipelineSettings['subtitleStyle']
  result.opedSeries = cleanShortText(input.opedSeries ?? result.opedSeries, 'opedSeries')
  result.translationBatchSize = cleanInteger(
    input.translationBatchSize ?? result.translationBatchSize,
    'translationBatchSize',
    0,
    100
  )
  result.translationContextWindow = cleanInteger(
    input.translationContextWindow ?? result.translationContextWindow,
    'translationContextWindow',
    0,
    50
  )
  return result
}

export interface SettingsRepository {
  get(): PipelineSettings
  save(value: unknown): PipelineSettings
  reset(): PipelineSettings
}

export function createSettingsRepository(): SettingsRepository {
  if (!store) {
    store = new StoreConstructor<SettingsStore>({
      name: 'desktop-settings',
      defaults: { settings: { ...DEFAULT_SETTINGS } }
    })
  }
  return {
    get: () => sanitizeSettings(store!.get('settings')),
    save: (value) => {
      const settings = sanitizeSettings(value)
      store!.set('settings', settings)
      return settings
    },
    reset: () => {
      const settings = { ...DEFAULT_SETTINGS }
      store!.set('settings', settings)
      return settings
    }
  }
}
