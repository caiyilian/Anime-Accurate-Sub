import { readFile, stat } from 'node:fs/promises'
import { join, parse } from 'node:path'
import type {
  PipelineJob,
  PipelineProgress,
  PipelineSettings,
  PipelineStageKey,
  PipelineStageProgress
} from '../shared/types'

export const STAGE_LABELS: Record<PipelineStageKey, string> = {
  prepare: '准备环境',
  extract_audio: '提取音频',
  japanese_subtitle: '读取日文字幕',
  asr: '日语语音识别',
  translate: '上下文翻译',
  multi_agent_review: '五 Agent 审查',
  mqm_quality_review: 'GEMBA-MQM',
  subtitle: '生成字幕',
  embed_subtitle: '嵌入视频',
  quality_check: '质量检查',
  completed: '已完成'
}

const STAGE_MARKER = /^\s*\[(extract_audio|japanese_subtitle|asr|translate|multi_agent_review|mqm_quality_review|subtitle|embed_subtitle|quality_check)]\s*$/i

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value * 10) / 10))
}

export function pipelineStagePlan(
  settings: PipelineSettings,
  useJapaneseSubtitle: boolean
): PipelineStageKey[] {
  const stages: PipelineStageKey[] = ['prepare']
  const sourceStages: PipelineStageKey[] = useJapaneseSubtitle
    ? ['japanese_subtitle']
    : ['extract_audio', 'asr']
  stages.push(...sourceStages)
  stages.push('translate')
  if (settings.multiAgentReview) stages.push('multi_agent_review')
  if (settings.mqmQualityReview) stages.push('mqm_quality_review')
  stages.push('subtitle', 'embed_subtitle')
  if (settings.qualityCheck) stages.push('quality_check')
  return stages
}

function stageEntries(plan: PipelineStageKey[]): PipelineStageProgress[] {
  return plan.map((key, index) => ({
    key,
    label: STAGE_LABELS[key],
    status: index === 0 ? 'running' : 'pending',
    percent: 0
  }))
}

export function createInitialProgress(
  settings: PipelineSettings,
  useJapaneseSubtitle: boolean,
  at = new Date().toISOString()
): PipelineProgress {
  const plan = pipelineStagePlan(settings, useJapaneseSubtitle)
  return {
    activeStage: plan[0],
    activeStageLabel: STAGE_LABELS[plan[0]],
    stagePercent: 0,
    overallPercent: 0,
    completedStages: 0,
    totalStages: plan.length,
    lastActivityAt: at,
    stages: stageEntries(plan)
  }
}

function withPlan(progress: PipelineProgress, plan: PipelineStageKey[]): PipelineProgress {
  const existing = new Map(progress.stages.map((stage) => [stage.key, stage]))
  const stages = plan.map((key) => existing.get(key) ?? {
    key,
    label: STAGE_LABELS[key],
    status: 'pending' as const,
    percent: 0
  })
  const active = stages.find((stage) => stage.status === 'running') ?? stages.find((stage) => stage.status === 'pending') ?? stages.at(-1)!
  return { ...progress, stages, totalStages: stages.length, activeStage: active.key, activeStageLabel: active.label }
}

function recalculate(progress: PipelineProgress, at: string): PipelineProgress {
  const completedStages = progress.stages.filter((stage) => stage.status === 'completed').length
  const active = progress.stages.find((stage) => stage.status === 'running')
  const stagePercent = active?.percent ?? (completedStages === progress.stages.length ? 100 : 0)
  const overallPercent = progress.stages.length
    ? clampPercent(((completedStages + stagePercent / 100) / progress.stages.length) * 100)
    : 100
  return {
    ...progress,
    activeStage: active?.key ?? (completedStages === progress.stages.length ? 'completed' : progress.activeStage),
    activeStageLabel: active?.label ?? (completedStages === progress.stages.length ? STAGE_LABELS.completed : progress.activeStageLabel),
    stagePercent,
    overallPercent: Math.max(progress.overallPercent, overallPercent),
    completedStages,
    totalStages: progress.stages.length,
    lastActivityAt: at
  }
}

function activateStage(
  original: PipelineProgress,
  key: PipelineStageKey,
  settings: PipelineSettings,
  at: string
): PipelineProgress {
  let progress = structuredClone(original)
  if (key === 'japanese_subtitle' && !progress.stages.some((stage) => stage.key === key)) {
    progress = withPlan(progress, pipelineStagePlan(settings, true))
  }
  const index = progress.stages.findIndex((stage) => stage.key === key)
  if (index < 0) return original
  const currentIndex = progress.stages.findIndex((stage) => stage.status === 'running')
  if (currentIndex > index) return original
  progress.stages = progress.stages.map((stage, stageIndex) => {
    if (stageIndex < index) return { ...stage, status: 'completed', percent: 100 }
    if (stageIndex === index) return { ...stage, status: 'running', percent: stage.status === 'completed' ? 100 : stage.percent }
    return stage.status === 'completed' ? stage : { ...stage, status: 'pending', percent: 0 }
  })
  return recalculate(progress, at)
}

function updateActivePercent(progress: PipelineProgress, percent: number, at: string): PipelineProgress {
  const next = structuredClone(progress)
  const active = next.stages.find((stage) => stage.status === 'running')
  if (!active) return progress
  active.percent = Math.max(active.percent, clampPercent(percent))
  return recalculate(next, at)
}

export function updateProgressFromLine(
  progress: PipelineProgress,
  line: string,
  settings: PipelineSettings,
  at = new Date().toISOString()
): PipelineProgress {
  const marker = line.match(STAGE_MARKER)
  if (marker) return activateStage(progress, marker[1].toLowerCase() as PipelineStageKey, settings, at)

  const pipelineSummary = line.match(/Pipeline:\s*(\d+)\s*\/\s*(\d+)\s*stages?\s*completed/i)
  if (pipelineSummary) {
    const completed = Math.min(Number(pipelineSummary[1]), progress.stages.length - 1)
    const next = structuredClone(progress)
    next.stages = next.stages.map((stage, index) =>
      index <= completed ? { ...stage, status: 'completed', percent: 100 } : stage
    )
    return recalculate(next, at)
  }

  const ratio = line.match(/(?:Translated:\s*|^\s*\[)(\d+)\s*\/\s*(\d+)/i)
  if (ratio && Number(ratio[2]) > 0) {
    return updateActivePercent(progress, (Number(ratio[1]) / Number(ratio[2])) * 100, at)
  }
  const percent = line.match(/(?:^|\s)(\d{1,3}(?:\.\d+)?)%/)
  if (percent) return updateActivePercent(progress, Number(percent[1]), at)
  return progress
}

export function completeProgress(progress: PipelineProgress, at = new Date().toISOString()): PipelineProgress {
  return {
    ...progress,
    activeStage: 'completed',
    activeStageLabel: STAGE_LABELS.completed,
    stagePercent: 100,
    overallPercent: 100,
    completedStages: progress.stages.length,
    lastActivityAt: at,
    stages: progress.stages.map((stage) => ({ ...stage, status: 'completed', percent: 100 }))
  }
}

export function failProgress(progress: PipelineProgress, at = new Date().toISOString()): PipelineProgress {
  const next = structuredClone(progress)
  const active = next.stages.find((stage) => stage.status === 'running')
  if (active) active.status = 'failed'
  return { ...next, lastActivityAt: at }
}

export function mergeProgress(current: PipelineProgress, incoming: PipelineProgress): PipelineProgress {
  if (incoming.overallPercent < current.overallPercent) return current
  const currentByKey = new Map(current.stages.map((stage) => [stage.key, stage]))
  const stages = incoming.stages.map((stage) => {
    const previous = currentByKey.get(stage.key)
    return previous && previous.percent > stage.percent ? { ...stage, percent: previous.percent } : stage
  })
  return { ...incoming, overallPercent: Math.max(current.overallPercent, incoming.overallPercent), stages }
}

export function sanitizeLogLine(line: string, maxLength = 4_000): string {
  const withoutAnsi = String(line).replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '')
  return withoutAnsi.length > maxLength ? `${withoutAnsi.slice(0, maxLength)}…[已截断]` : withoutAnsi
}

async function jsonArrayLength(path: string): Promise<number> {
  try {
    const value = JSON.parse(await readFile(path, 'utf8'))
    return Array.isArray(value) ? value.length : 0
  } catch {
    return 0
  }
}

async function jsonlLength(path: string): Promise<number> {
  try {
    return (await readFile(path, 'utf8')).split(/\r?\n/).filter((line) => line.trim()).length
  } catch {
    return 0
  }
}

async function newestActivity(paths: string[], fallback: string): Promise<string> {
  let latest = new Date(fallback).getTime() || 0
  for (const path of paths) {
    try {
      latest = Math.max(latest, (await stat(path)).mtimeMs)
    } catch {
      // Optional progress artifacts do not all exist in every pipeline mode.
    }
  }
  return latest ? new Date(latest).toISOString() : fallback
}

function outputRootFromJob(job: PipelineJob): string {
  const index = job.command?.args.indexOf('--output-dir') ?? -1
  return index >= 0 ? job.command!.args[index + 1] : job.settings.outputRoot
}

export async function readProgressFromFiles(job: PipelineJob): Promise<PipelineProgress> {
  const outputRoot = outputRootFromJob(job)
  if (!outputRoot) return job.progress
  const workDir = join(outputRoot, parse(job.video.name).name)
  let checkpoint: Record<string, { status?: string }> = {}
  let checkpointTime = job.progress.lastActivityAt
  try {
    checkpoint = JSON.parse(await readFile(join(workDir, 'checkpoint.json'), 'utf8'))
    checkpointTime = (await stat(join(workDir, 'checkpoint.json'))).mtime.toISOString()
  } catch {
    // The first stage may not have produced its checkpoint yet.
  }
  const useJapanese = Boolean(checkpoint.japanese_subtitle) || job.progress.stages.some((stage) => stage.key === 'japanese_subtitle')
  const plan = pipelineStagePlan(job.settings, useJapanese)
  const next = createInitialProgress(job.settings, useJapanese, checkpointTime)
  const hasCheckpoint = Object.keys(checkpoint).length > 0
  next.stages = stageEntries(plan).map((stage) => {
    if (stage.key === 'prepare' && hasCheckpoint) {
      return { ...stage, status: 'completed', percent: 100 }
    }
    const status = checkpoint[stage.key]?.status
    return status === 'completed'
      ? { ...stage, status: 'completed', percent: 100 }
      : status === 'failed'
        ? { ...stage, status: 'failed', percent: stage.percent }
        : stage
  })
  const firstIncomplete = next.stages.findIndex((stage) => stage.status !== 'completed')
  if (firstIncomplete >= 0 && next.stages[firstIncomplete].status !== 'failed') {
    next.stages[firstIncomplete] = { ...next.stages[firstIncomplete], status: 'running' }
  }

  const sourceTotal = await jsonArrayLength(join(workDir, 'asr_results.json'))
  const translated = await jsonArrayLength(join(workDir, 'translated.json'))
  const reviewed = await jsonlLength(join(workDir, 'multi_agent_review.progress.jsonl'))
  const mqmReviewed = await jsonlLength(join(workDir, 'mqm_quality_review.progress.jsonl'))
  checkpointTime = await newestActivity(
    [
      join(workDir, 'checkpoint.json'),
      join(workDir, 'translated.json'),
      join(workDir, 'multi_agent_review.progress.jsonl'),
      join(workDir, 'mqm_quality_review.progress.jsonl')
    ],
    checkpointTime
  )
  const ratios: Partial<Record<PipelineStageKey, [number, number]>> = {
    translate: [translated, sourceTotal],
    multi_agent_review: [reviewed, translated],
    mqm_quality_review: [mqmReviewed, translated]
  }
  for (const stage of next.stages) {
    const ratio = ratios[stage.key]
    if (ratio && ratio[1] > 0 && stage.status !== 'completed') {
      stage.percent = clampPercent((ratio[0] / ratio[1]) * 100)
    }
  }
  return mergeProgress(job.progress, recalculate(next, checkpointTime))
}
