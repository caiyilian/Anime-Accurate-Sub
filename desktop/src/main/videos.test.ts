// @vitest-environment node
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { inspectVideoPaths } from './videos'

let directory = ''

afterEach(async () => {
  if (directory) await rm(directory, { recursive: true, force: true })
  directory = ''
})

describe('inspectVideoPaths', () => {
  it('returns normalized metadata and rejects duplicates and unsupported files', async () => {
    directory = await mkdtemp(join(tmpdir(), 'anime-sub-desktop-'))
    const video = join(directory, 'episode 01.mp4')
    const text = join(directory, 'notes.txt')
    await writeFile(video, 'video')
    await writeFile(text, 'text')

    const result = await inspectVideoPaths([video, video, text, join(directory, 'missing.mkv')])
    expect(result.videos).toHaveLength(1)
    expect(result.videos[0]).toMatchObject({ path: video, name: 'episode 01.mp4', size: 5 })
    expect(result.rejected.map((item) => item.reason)).toEqual([
      '本次选择中重复',
      '不支持的视频格式',
      '文件不存在或不可读取'
    ])
  })
})
