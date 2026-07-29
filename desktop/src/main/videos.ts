import { createHash } from 'node:crypto'
import { stat } from 'node:fs/promises'
import { basename, extname, isAbsolute, normalize } from 'node:path'
import type { RejectedVideoInput, VideoInput, VideoInspectionResult } from '../shared/types'

const VIDEO_EXTENSIONS = new Set(['.mp4', '.mkv', '.avi', '.mov', '.webm'])
const MAX_VIDEO_INPUTS = 100

function rejected(path: string, reason: string): RejectedVideoInput {
  return { path, reason }
}

export async function inspectVideoPaths(value: unknown): Promise<VideoInspectionResult> {
  if (!Array.isArray(value)) throw new TypeError('视频路径必须是数组')
  if (value.length > MAX_VIDEO_INPUTS) throw new RangeError(`一次最多添加 ${MAX_VIDEO_INPUTS} 个视频`)

  const videos: VideoInput[] = []
  const rejectedItems: RejectedVideoInput[] = []
  const seen = new Set<string>()
  for (const raw of value) {
    if (typeof raw !== 'string' || !raw.trim() || raw.includes('\0') || !isAbsolute(raw)) {
      rejectedItems.push(rejected(String(raw ?? ''), '必须是绝对文件路径'))
      continue
    }
    const path = normalize(raw)
    const key = process.platform === 'win32' ? path.toLocaleLowerCase('en-US') : path
    if (seen.has(key)) {
      rejectedItems.push(rejected(path, '本次选择中重复'))
      continue
    }
    seen.add(key)
    if (!VIDEO_EXTENSIONS.has(extname(path).toLocaleLowerCase('en-US'))) {
      rejectedItems.push(rejected(path, '不支持的视频格式'))
      continue
    }
    try {
      const info = await stat(path)
      if (!info.isFile()) {
        rejectedItems.push(rejected(path, '不是普通文件'))
        continue
      }
      videos.push({
        id: createHash('sha256').update(key).digest('hex').slice(0, 16),
        path,
        name: basename(path),
        size: info.size,
        modifiedAt: info.mtime.toISOString()
      })
    } catch {
      rejectedItems.push(rejected(path, '文件不存在或不可读取'))
    }
  }
  return { videos, rejected: rejectedItems }
}
