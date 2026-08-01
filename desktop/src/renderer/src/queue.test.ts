import { describe, expect, it } from 'vitest'
import type { VideoInput } from '../../shared/types'
import { formatFileSize, mergeVideoQueue, moveQueueItem } from './queue'

const video = (id: string, path: string): VideoInput => ({
  id,
  path,
  name: `${id}.mp4`,
  size: 1024,
  modifiedAt: '2026-07-29T00:00:00.000Z'
})

describe('video queue helpers', () => {
  it('deduplicates normalized Windows paths and preserves insertion order', () => {
    const first = mergeVideoQueue(
      [],
      [video('1', 'E:\\Anime\\01.mp4'), video('2', 'E:\\Anime\\02.mp4')]
    )
    const second = mergeVideoQueue(first.queue, [
      video('3', 'e:\\anime\\01.mp4'),
      video('4', 'E:\\Anime\\03.mp4')
    ])
    expect(second.queue.map((item) => item.id)).toEqual(['1', '2', '4'])
    expect(second.duplicates).toBe(1)
  })

  it('moves items within bounds and formats file sizes', () => {
    const queue = mergeVideoQueue([], [video('1', '1.mp4'), video('2', '2.mp4')]).queue
    expect(moveQueueItem(queue, '2', -1).map((item) => item.id)).toEqual(['2', '1'])
    expect(moveQueueItem(queue, '1', -1)).toBe(queue)
    expect(formatFileSize(1024)).toBe('1.0 KB')
  })
})
