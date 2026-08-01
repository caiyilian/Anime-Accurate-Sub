import type { Configuration } from 'electron-builder'

const config: Configuration = {
  appId: 'io.github.caiyilian.anime-accurate-sub',
  productName: 'Anime Accurate Sub',
  copyright: 'Copyright © 2026 Anime Accurate Sub contributors',
  asar: true,
  directories: {
    output: 'release',
    buildResources: 'build'
  },
  files: ['out/**/*', 'package.json'],
  extraResources: [
    {
      from: '../scripts',
      to: 'backend/scripts',
      filter: [
        'anime_sub.py',
        'asr_engine.py',
        'checkpoint.py',
        'extract_subs.py',
        'glossary.py',
        'hardware.py',
        'mqm_quality_review.py',
        'oped_detector.py',
        'plugin_system.py',
        'quality_check.py',
        'review_agents.py',
        'series_memory.py',
        'subtitle_gen.py',
        'translation_engine.py',
        'translation_memory.py',
        'translator_adapter.py'
      ]
    },
    {
      from: '../config',
      to: 'backend/config',
      filter: [
        'quality_final_adjudication.sensenova.json',
        'quality_mqm.sensenova.json',
        'quality_review.sensenova.json',
        'translator.sakura-remote.example.json'
      ]
    },
    { from: '../pyproject.toml', to: 'backend/pyproject.toml' }
  ],
  win: {
    target: [{ target: 'nsis', arch: ['x64'] }],
    icon: 'build/icon.png',
    executableName: 'anime-accurate-sub',
    artifactName: '${productName}-Setup-${version}-${arch}.${ext}'
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: 'Anime Accurate Sub',
    uninstallDisplayName: 'Anime Accurate Sub',
    deleteAppDataOnUninstall: false,
    runAfterFinish: true
  }
}

export default config
