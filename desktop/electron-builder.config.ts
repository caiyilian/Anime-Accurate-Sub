import type { Configuration } from 'electron-builder'

const config: Configuration = {
  appId: 'io.github.caiyilian.anime-accurate-sub',
  productName: 'Anime Accurate Sub',
  directories: {
    output: 'release'
  },
  files: ['out/**/*', 'package.json'],
  win: {
    target: ['nsis']
  },
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true
  }
}

export default config
