export const IPC_CHANNELS = Object.freeze({
  getSettings: 'settings:get',
  saveSettings: 'settings:save',
  resetSettings: 'settings:reset',
  pickVideos: 'dialog:pick-videos',
  pickFile: 'dialog:pick-file',
  pickDirectory: 'dialog:pick-directory',
  inspectVideos: 'videos:inspect',
  runDiagnostics: 'diagnostics:run',
  previewCommand: 'pipeline:preview-command',
  startPipeline: 'pipeline:start',
  cancelPipeline: 'pipeline:cancel',
  resumePipeline: 'pipeline:resume',
  getPipelineSnapshot: 'pipeline:get-snapshot',
  pipelineEvent: 'pipeline:event'
})
