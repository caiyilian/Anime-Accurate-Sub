import log from 'electron-log/main'

export function initializeLogging(): string {
  log.initialize()
  log.transports.file.level = 'info'
  log.transports.console.level = 'info'
  log.info('Anime Accurate Sub desktop main process starting')
  return log.transports.file.getFile().path
}

export { log }
