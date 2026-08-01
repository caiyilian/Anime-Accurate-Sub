import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type {
  PipelineJob,
  PipelineLogLine,
  PipelineProgress,
  PipelineSettings
} from '../../shared/types'
import LogConsole from './LogConsole'

const settings: PipelineSettings = {
  projectRoot: '',
  pythonPath: '',
  outputRoot: '',
  backend: 'sakura',
  asrBackend: 'anime_whisper',
  subtitleStyle: 'anime',
  translationConfigPath: '',
  memoryPath: '',
  glossaryPath: '',
  translationMemoryPath: '',
  japaneseSubtitleDir: '',
  speakerMapPath: '',
  opedSeries: '',
  translationBatchSize: 0,
  translationContextWindow: 3,
  preferJapaneseSubtitles: true,
  qualityCheck: true,
  multiAgentReview: true,
  mqmQualityReview: true,
  autoHardware: false,
  opedBestEffort: true,
  continueOnError: true
}
const progress: PipelineProgress = {
  activeStage: 'translate',
  activeStageLabel: '上下文翻译',
  stagePercent: 50,
  overallPercent: 40,
  completedStages: 3,
  totalStages: 9,
  lastActivityAt: '2026-07-29T00:00:00.000Z',
  stages: [{ key: 'translate', label: '上下文翻译', status: 'running', percent: 50 }]
}

const job: PipelineJob = {
  id: 'job-1',
  video: {
    id: 'video',
    path: 'E:\\01.mp4',
    name: '01.mp4',
    size: 1,
    modifiedAt: '2026-07-29T00:00:00.000Z'
  },
  japaneseSubtitlePath: '',
  settings,
  status: 'running',
  progress
}

const logs: PipelineLogLine[] = [
  { at: '2026-07-29T00:00:00.000Z', jobId: 'job-1', stream: 'stdout', line: 'Translated: 1/2' },
  { at: '2026-07-29T00:00:01.000Z', jobId: 'job-1', stream: 'stderr', line: 'warning line' }
]

describe('LogConsole', () => {
  it('filters streams, searches, toggles following and clears only the view', () => {
    render(<LogConsole logs={logs} jobs={[job]} />)
    expect(screen.getByText('Translated: 1/2')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('日志流筛选'), { target: { value: 'stderr' } })
    expect(screen.queryByText('Translated: 1/2')).not.toBeInTheDocument()
    expect(screen.getByText('warning line')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '自动跟随：开' }))
    expect(screen.getByRole('button', { name: '自动跟随：关' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '清空视图' }))
    expect(screen.getByText('暂无符合条件的日志。')).toBeInTheDocument()
  })
})
