import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  const settings = {
    projectRoot: '', pythonPath: '', outputRoot: '', backend: 'sakura', asrBackend: 'anime_whisper',
    subtitleStyle: 'anime', translationConfigPath: '', memoryPath: '', glossaryPath: '',
    translationMemoryPath: '', japaneseSubtitleDir: '', speakerMapPath: '', opedSeries: '',
    translationBatchSize: 0, translationContextWindow: 3, preferJapaneseSubtitles: true,
    qualityCheck: true, multiAgentReview: true, mqmQualityReview: true, autoHardware: false,
    opedBestEffort: true, continueOnError: true
  } as const

  beforeEach(() => {
    Object.defineProperty(window, 'desktopApi', {
      configurable: true,
      value: {
        platform: 'win32',
        versions: { chrome: '1.0.0', electron: '43.2.0', node: '24.6.0' },
        getSettings: async () => settings,
        saveSettings: async () => settings,
        resetSettings: async () => settings,
        pickVideos: async () => ['E:\\anime\\01.mp4'],
        pickFile: async () => null,
        pickDirectory: async () => null,
        getPathForFile: () => '',
        inspectVideos: async () => ({
          videos: [{
            id: 'episode-1',
            path: 'E:\\anime\\01.mp4',
            name: '01.mp4',
            size: 1024,
            modifiedAt: '2026-07-29T00:00:00.000Z'
          }],
          rejected: []
        }),
        runDiagnostics: async () => ({
          ready: true,
          checkedAt: '2026-07-29T00:00:00.000Z',
          checks: [{ id: 'python', label: 'Python', status: 'ok', detail: 'Python 3.11' }],
          resolved: { projectRoot: 'E:\\repo', pythonPath: 'python', outputRoot: 'E:\\out', ffmpegPath: 'ffmpeg' },
          logPath: 'E:\\logs\\desktop.log'
        }),
        previewCommand: async () => ({ executable: 'python', args: [], cwd: 'E:\\repo', display: 'python' }),
        startPipeline: async () => { throw new Error('not used') },
        cancelPipeline: async () => null,
        resumePipeline: async () => { throw new Error('not used') },
        getPipelineSnapshot: async () => null,
        onPipelineEvent: () => () => undefined
      }
    })
  })

  it('renders the workbench and adds validated videos from the native picker', async () => {
    render(<App />)

    expect(screen.getByTestId('desktop-root')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '字幕生成工作台' })).toBeInTheDocument()
    expect(await screen.findByLabelText(/质量检查/)).toBeChecked()
    expect(screen.getByLabelText(/五 Agent 审查/)).toBeChecked()
    await waitFor(() => expect(screen.getByText('Python · OK')).toBeInTheDocument())
    expect(screen.getByText('READY')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('video-drop-zone'))
    await waitFor(() => expect(screen.getByText('01.mp4')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('python')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '开始完整流程' })).toBeEnabled()
  })
})
