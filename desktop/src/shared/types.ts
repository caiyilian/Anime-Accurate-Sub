export const TRANSLATION_BACKENDS = ['sakura', 'qwen', 'galtransl', 'external'] as const
export const ASR_BACKENDS = ['anime_whisper'] as const
export const SUBTITLE_STYLES = ['anime', 'anime_bilingual', 'classic', 'karaoke'] as const

export type TranslationBackend = (typeof TRANSLATION_BACKENDS)[number]
export type AsrBackend = (typeof ASR_BACKENDS)[number]
export type SubtitleStyle = (typeof SUBTITLE_STYLES)[number]

export interface PipelineSettings {
  projectRoot: string
  pythonPath: string
  outputRoot: string
  backend: TranslationBackend
  asrBackend: AsrBackend
  subtitleStyle: SubtitleStyle
  translationConfigPath: string
  memoryPath: string
  glossaryPath: string
  translationMemoryPath: string
  japaneseSubtitleDir: string
  speakerMapPath: string
  opedSeries: string
  translationBatchSize: number
  translationContextWindow: number
  preferJapaneseSubtitles: boolean
  qualityCheck: boolean
  multiAgentReview: boolean
  mqmQualityReview: boolean
  autoHardware: boolean
  opedBestEffort: boolean
}

export interface DiagnosticCheck {
  id: string
  label: string
  status: 'ok' | 'warning' | 'error'
  detail: string
  path?: string
}

export interface DiagnosticsResult {
  ready: boolean
  checkedAt: string
  checks: DiagnosticCheck[]
  resolved: {
    projectRoot: string
    pythonPath: string
    outputRoot: string
    ffmpegPath: string
  }
  logPath: string
}

export interface CommandPreviewRequest {
  videoPath: string
  japaneseSubtitlePath?: string
  settings?: PipelineSettings
}

export interface CommandPreview {
  executable: string
  args: string[]
  cwd: string
  display: string
}

export interface VideoInput {
  id: string
  path: string
  name: string
  size: number
  modifiedAt: string
}

export interface RejectedVideoInput {
  path: string
  reason: string
}

export interface VideoInspectionResult {
  videos: VideoInput[]
  rejected: RejectedVideoInput[]
}

export type FilePickerKind = 'json' | 'python' | 'subtitle' | 'video'

export interface DesktopApi {
  platform: string
  versions: Readonly<{
    chrome: string
    electron: string
    node: string
  }>
  getSettings: () => Promise<PipelineSettings>
  saveSettings: (settings: PipelineSettings) => Promise<PipelineSettings>
  resetSettings: () => Promise<PipelineSettings>
  pickVideos: () => Promise<string[]>
  pickFile: (kind: FilePickerKind) => Promise<string | null>
  pickDirectory: () => Promise<string | null>
  getPathForFile: (file: unknown) => string
  inspectVideos: (paths: string[]) => Promise<VideoInspectionResult>
  runDiagnostics: () => Promise<DiagnosticsResult>
  previewCommand: (request: CommandPreviewRequest) => Promise<CommandPreview>
}
