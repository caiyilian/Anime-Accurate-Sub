import { spawn } from 'node:child_process'
import { constants, existsSync } from 'node:fs'
import { access, mkdir, unlink, writeFile } from 'node:fs/promises'
import { delimiter, join, normalize, resolve } from 'node:path'
import type { DiagnosticCheck, DiagnosticsResult, PipelineSettings } from '../shared/types'

export interface DiagnosticContext {
  appPath: string
  resourcesPath: string
  env?: NodeJS.ProcessEnv
  logPath?: string
}

export interface ProbeResult {
  ok: boolean
  detail: string
}

export function projectRootCandidates(settings: PipelineSettings, context: DiagnosticContext): string[] {
  const env = context.env ?? process.env
  const candidates = [
    settings.projectRoot,
    env.ANIME_ACCURATE_SUB_ROOT ?? '',
    join(context.resourcesPath, 'backend'),
    resolve(context.appPath, '..'),
    resolve(context.appPath, '../..'),
    process.cwd()
  ]
  return [...new Set(candidates.filter(Boolean).map((candidate) => normalize(candidate)))]
}

export function resolveProjectRoot(settings: PipelineSettings, context: DiagnosticContext): string {
  return (
    projectRootCandidates(settings, context).find((candidate) =>
      existsSync(join(candidate, 'scripts', 'anime_sub.py'))
    ) ?? ''
  )
}

export function pythonCandidates(settings: PipelineSettings, projectRoot: string, env = process.env): string[] {
  const fromPath = (env.PATH ?? '')
    .split(delimiter)
    .filter(Boolean)
    .flatMap((directory) => [join(directory, 'python.exe'), join(directory, 'python')])
  const candidates = [
    settings.pythonPath,
    env.ANIME_ACCURATE_SUB_PYTHON ?? '',
    projectRoot ? join(projectRoot, '.venv', 'Scripts', 'python.exe') : '',
    projectRoot ? join(projectRoot, 'venv', 'Scripts', 'python.exe') : '',
    'D:\\miniconda3\\python.exe',
    ...fromPath,
    'python.exe',
    'python'
  ]
  return [...new Set(candidates.filter(Boolean).map((candidate) => normalize(candidate)))]
}

export function probeExecutable(
  executable: string,
  args: string[],
  timeoutMs = 5_000
): Promise<ProbeResult> {
  return new Promise((resolveProbe) => {
    let output = ''
    let settled = false
    const child = spawn(executable, args, {
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe']
    })
    const finish = (result: ProbeResult): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolveProbe(result)
    }
    child.stdout.on('data', (chunk) => (output += String(chunk)))
    child.stderr.on('data', (chunk) => (output += String(chunk)))
    child.once('error', (error) => finish({ ok: false, detail: error.message }))
    child.once('close', (code) =>
      finish({ ok: code === 0, detail: output.trim().split(/\r?\n/, 1)[0] || `退出码 ${code}` })
    )
    const timer = setTimeout(() => {
      child.kill()
      finish({ ok: false, detail: `探测超时（${timeoutMs}ms）` })
    }, timeoutMs)
  })
}

async function findPython(candidates: string[]): Promise<{ path: string; detail: string }> {
  for (const candidate of candidates) {
    const result = await probeExecutable(candidate, ['--version'])
    if (result.ok) return { path: candidate, detail: result.detail }
  }
  return { path: '', detail: '未找到可执行的 Python' }
}

async function checkWritableDirectory(path: string): Promise<ProbeResult> {
  const probePath = join(path, `.desktop-write-probe-${process.pid}-${Date.now()}`)
  try {
    await mkdir(path, { recursive: true })
    await access(path, constants.W_OK)
    await writeFile(probePath, 'ok', 'utf8')
    await unlink(probePath)
    return { ok: true, detail: '目录可写' }
  } catch (error) {
    await unlink(probePath).catch(() => undefined)
    return { ok: false, detail: error instanceof Error ? error.message : String(error) }
  }
}

export async function runDiagnostics(
  settings: PipelineSettings,
  context: DiagnosticContext
): Promise<DiagnosticsResult> {
  const projectRoot = resolveProjectRoot(settings, context)
  const checks: DiagnosticCheck[] = []
  checks.push({
    id: 'project-root',
    label: '项目根目录',
    status: projectRoot ? 'ok' : 'error',
    detail: projectRoot ? '已找到 scripts/anime_sub.py' : '未找到有效项目根目录',
    path: projectRoot || undefined
  })

  const python = await findPython(pythonCandidates(settings, projectRoot, context.env))
  checks.push({
    id: 'python',
    label: 'Python',
    status: python.path ? 'ok' : 'error',
    detail: python.detail,
    path: python.path || undefined
  })

  const ffmpeg = await probeExecutable('ffmpeg', ['-version'])
  checks.push({
    id: 'ffmpeg',
    label: 'FFmpeg',
    status: ffmpeg.ok ? 'ok' : 'error',
    detail: ffmpeg.detail,
    path: ffmpeg.ok ? 'ffmpeg' : undefined
  })

  const outputRoot = settings.outputRoot || (projectRoot ? join(projectRoot, 'output', 'desktop') : '')
  const writable = outputRoot
    ? await checkWritableDirectory(outputRoot)
    : { ok: false, detail: '项目根目录和输出目录均未设置' }
  checks.push({
    id: 'output-root',
    label: '输出目录',
    status: writable.ok ? 'ok' : 'error',
    detail: writable.detail,
    path: outputRoot || undefined
  })

  const configFiles = [
    ['review-config', '多 Agent 审查配置', 'quality_review.sensenova.json'],
    ['mqm-config', 'MQM 配置', 'quality_mqm.sensenova.json']
  ] as const
  for (const [id, label, file] of configFiles) {
    const path = projectRoot ? join(projectRoot, 'config', file) : ''
    checks.push({
      id,
      label,
      status: path && existsSync(path) ? 'ok' : 'warning',
      detail: path && existsSync(path) ? '配置文件存在' : '配置文件缺失；对应高级审查不可用',
      path: path || undefined
    })
  }

  return {
    ready: checks.filter((check) => ['project-root', 'python', 'ffmpeg', 'output-root'].includes(check.id))
      .every((check) => check.status === 'ok'),
    checkedAt: new Date().toISOString(),
    checks,
    resolved: {
      projectRoot,
      pythonPath: python.path,
      outputRoot,
      ffmpegPath: ffmpeg.ok ? 'ffmpeg' : ''
    },
    logPath: context.logPath ?? ''
  }
}
