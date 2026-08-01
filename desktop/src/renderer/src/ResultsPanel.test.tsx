import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DesktopApi, ResultBundle } from '../../shared/types'
import ResultsPanel from './ResultsPanel'

const bundles: ResultBundle[] = [
  {
    jobId: 'job',
    videoName: 'episode.mp4',
    jobStatus: 'succeeded',
    artifacts: [
      {
        id: 'subtitle',
        kind: 'subtitle-srt',
        label: 'SRT 字幕',
        name: 'episode.srt',
        size: 42,
        modifiedAt: '2026-07-29T00:00:00.000Z'
      },
      {
        id: 'video',
        kind: 'video',
        label: '嵌字视频',
        name: 'episode_subs.mp4',
        size: 1024,
        modifiedAt: '2026-07-29T00:00:00.000Z',
        mediaUrl: 'aas-media://artifact/1234567890abcdef1234567890abcdef'
      }
    ]
  }
]

describe('ResultsPanel', () => {
  it('renders the registered media URL and reads text only through the artifact API', async () => {
    const api = {
      readResultArtifact: vi.fn(async () => ({
        id: 'subtitle',
        name: 'episode.srt',
        content: '你好，世界'
      })),
      openResultDirectory: vi.fn(async () => undefined),
      exportPipelineLog: vi.fn(async () => null)
    } as unknown as DesktopApi
    render(<ResultsPanel bundles={bundles} api={api} onRefresh={() => undefined} />)
    expect(screen.getByLabelText('episode.mp4 嵌字视频')).toHaveAttribute(
      'src',
      bundles[0].artifacts[1].mediaUrl
    )
    fireEvent.click(screen.getByRole('button', { name: /SRT 字幕/ }))
    await waitFor(() => expect(screen.getByText('你好，世界')).toBeInTheDocument())
    expect(api.readResultArtifact).toHaveBeenCalledWith('subtitle')
  })
})
