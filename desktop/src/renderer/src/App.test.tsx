import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  const settings = {
    projectRoot: '', pythonPath: '', outputRoot: '', backend: 'sakura', asrBackend: 'anime_whisper',
    subtitleStyle: 'anime', translationConfigPath: '', memoryPath: '', glossaryPath: '',
    translationMemoryPath: '', japaneseSubtitleDir: '', speakerMapPath: '', opedSeries: '',
    translationBatchSize: 0, translationContextWindow: 3, preferJapaneseSubtitles: true,
    qualityCheck: true, multiAgentReview: true, mqmQualityReview: true, autoHardware: false,
    opedBestEffort: true
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
        pickVideos: async () => [],
        pickFile: async () => null,
        pickDirectory: async () => null,
        runDiagnostics: async () => ({
          ready: true,
          checkedAt: '2026-07-29T00:00:00.000Z',
          checks: [{ id: 'python', label: 'Python', status: 'ok', detail: 'Python 3.11' }],
          resolved: { projectRoot: 'E:\\repo', pythonPath: 'python', outputRoot: 'E:\\out', ffmpegPath: 'ffmpeg' },
          logPath: 'E:\\logs\\desktop.log'
        }),
        previewCommand: async () => ({ executable: 'python', args: [], cwd: 'E:\\repo', display: 'python' })
      }
    })
  })

  it('renders settings and completed environment diagnostics', async () => {
    render(<App />)

    expect(screen.getByTestId('desktop-root')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '设置与运行环境' })).toBeInTheDocument()
    expect(screen.getByText('43.2.0')).toBeInTheDocument()
    expect(screen.getByText('win32')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Python 3.11')).toBeInTheDocument())
    expect(screen.getByText('READY')).toBeInTheDocument()
  })
})
