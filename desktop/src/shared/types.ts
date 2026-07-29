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
  continueOnError: boolean
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

export type PipelineJobStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'canceled'
  | 'interrupted'

export type PipelineRunStatus =
  | 'idle'
  | 'running'
  | 'canceling'
  | 'canceled'
  | 'completed'
  | 'failed'
  | 'interrupted'

export type PipelineStageKey =
  | 'prepare'
  | 'extract_audio'
  | 'japanese_subtitle'
  | 'asr'
  | 'translate'
  | 'multi_agent_review'
  | 'mqm_quality_review'
  | 'subtitle'
  | 'embed_subtitle'
  | 'quality_check'
  | 'completed'

export interface PipelineStageProgress {
  key: PipelineStageKey
  label: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  percent: number
}

export interface PipelineProgress {
  activeStage: PipelineStageKey
  activeStageLabel: string
  stagePercent: number
  overallPercent: number
  completedStages: number
  totalStages: number
  lastActivityAt: string
  stages: PipelineStageProgress[]
}

export interface PipelineLogLine {
  at: string
  jobId: string
  stream: 'stdout' | 'stderr' | 'system'
  line: string
}

export interface PipelineJob {
  id: string
  video: VideoInput
  japaneseSubtitlePath: string
  settings: PipelineSettings
  status: PipelineJobStatus
  command?: Pick<CommandPreview, 'executable' | 'args' | 'cwd' | 'display'>
  startedAt?: string
  finishedAt?: string
  exitCode?: number | null
  error?: string
  progress: PipelineProgress
}

export interface PipelineSnapshot {
  schemaVersion: 1
  runId: string
  status: PipelineRunStatus
  continueOnError: boolean
  createdAt: string
  updatedAt: string
  startedAt?: string
  finishedAt?: string
  currentJobId?: string
  overallPercent: number
  jobs: PipelineJob[]
  logs: PipelineLogLine[]
}

export interface StartPipelineRequest {
  videos: Array<{ path: string; japaneseSubtitlePath?: string }>
  settings: PipelineSettings
}

export type PipelineEvent =
  | { type: 'snapshot'; snapshot: PipelineSnapshot | null }
  | { type: 'log'; runId: string; log: PipelineLogLine }

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
  startPipeline: (request: StartPipelineRequest) => Promise<PipelineSnapshot>
  cancelPipeline: () => Promise<PipelineSnapshot | null>
  resumePipeline: () => Promise<PipelineSnapshot>
  getPipelineSnapshot: () => Promise<PipelineSnapshot | null>
  onPipelineEvent: (listener: (event: PipelineEvent) => void) => () => void
}
