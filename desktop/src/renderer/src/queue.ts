import type { VideoInput } from '../../shared/types'

export interface QueuedVideo extends VideoInput {
  japaneseSubtitlePath: string
}

function pathKey(path: string): string {
  return path.toLocaleLowerCase('en-US')
}

export function mergeVideoQueue(
  current: QueuedVideo[],
  incoming: VideoInput[]
): { queue: QueuedVideo[]; duplicates: number } {
  const seen = new Set(current.map((item) => pathKey(item.path)))
  const queue = [...current]
  let duplicates = 0
  for (const video of incoming) {
    const key = pathKey(video.path)
    if (seen.has(key)) {
      duplicates += 1
      continue
    }
    seen.add(key)
    queue.push({ ...video, japaneseSubtitlePath: '' })
  }
  return { queue, duplicates }
}

export function moveQueueItem(queue: QueuedVideo[], id: string, offset: -1 | 1): QueuedVideo[] {
  const index = queue.findIndex((item) => item.id === id)
  const target = index + offset
  if (index < 0 || target < 0 || target >= queue.length) return queue
  const next = [...queue]
  ;[next[index], next[target]] = [next[target], next[index]]
  return next
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}
