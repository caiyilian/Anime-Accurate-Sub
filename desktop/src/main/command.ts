import { existsSync } from 'node:fs'
import { isAbsolute, join, normalize } from 'node:path'
import type {
  CommandPreview,
  CommandPreviewRequest,
  DiagnosticsResult,
  PipelineSettings
} from '../shared/types'
import { sanitizeSettings } from './settings'

function assertAbsoluteFile(path: string, field: string, requireExisting = true): string {
  if (typeof path !== 'string' || !isAbsolute(path) || path.includes('\0')) {
    throw new TypeError(`${field} 必须是有效绝对路径`)
  }
  const normalized = normalize(path)
  if (requireExisting && !existsSync(normalized)) throw new TypeError(`${field} 不存在`)
  return normalized
}

function displayArgument(value: string): string {
  return /^[A-Za-z0-9_./:\\=-]+$/.test(value) ? value : JSON.stringify(value)
}

function addPathOption(args: string[], flag: string, value: string): void {
  if (value) args.push(flag, value)
}

export function buildPipelineCommand(
  request: CommandPreviewRequest,
  storedSettings: PipelineSettings,
  diagnostics: DiagnosticsResult,
  requireExistingVideo = true
): CommandPreview {
  const settings = sanitizeSettings(request.settings ?? storedSettings)
  const videoPath = assertAbsoluteFile(request.videoPath, 'videoPath', requireExistingVideo)
  const projectRoot = diagnostics.resolved.projectRoot
  const executable = diagnostics.resolved.pythonPath
  const outputRoot = settings.outputRoot || diagnostics.resolved.outputRoot
  if (!projectRoot || !executable || !outputRoot) throw new Error('环境诊断尚未通过')

  const args = [
    join(projectRoot, 'scripts', 'anime_sub.py'),
    videoPath,
    '--output-dir',
    outputRoot,
    '--backend',
    settings.backend,
    '--asr-backend',
    settings.asrBackend,
    '--subtitle-style',
    settings.subtitleStyle,
    '--translation-context-window',
    String(settings.translationContextWindow)
  ]
  if (settings.translationBatchSize > 0) {
    args.push('--translation-batch-size', String(settings.translationBatchSize))
  }
  addPathOption(args, '--config', settings.translationConfigPath)
  addPathOption(args, '--memory', settings.memoryPath)
  addPathOption(args, '--glossary', settings.glossaryPath)
  addPathOption(args, '--translation-memory', settings.translationMemoryPath)
  addPathOption(args, '--japanese-subtitle-dir', settings.japaneseSubtitleDir)
  addPathOption(args, '--speaker-map', settings.speakerMapPath)
  if (request.japaneseSubtitlePath) {
    args.push(
      '--japanese-subtitle',
      assertAbsoluteFile(request.japaneseSubtitlePath, 'japaneseSubtitlePath')
    )
  }
  if (settings.preferJapaneseSubtitles) args.push('--prefer-japanese-subtitles')
  if (settings.qualityCheck) args.push('--quality-check')
  if (settings.multiAgentReview) {
    args.push(
      '--multi-agent-review',
      '--review-config',
      join(projectRoot, 'config', 'quality_review.sensenova.json')
    )
  }
  if (settings.mqmQualityReview) {
    args.push(
      '--mqm-quality-review',
      '--mqm-config',
      join(projectRoot, 'config', 'quality_mqm.sensenova.json')
    )
  }
  if (settings.autoHardware) args.push('--auto')
  if (settings.opedSeries) args.push('--oped-series', settings.opedSeries)
  if (settings.opedBestEffort) args.push('--oped-best-effort')

  return {
    executable,
    args,
    cwd: projectRoot,
    display: [executable, ...args].map(displayArgument).join(' ')
  }
}
