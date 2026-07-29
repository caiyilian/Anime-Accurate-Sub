/// <reference types="vite/client" />

interface DesktopApi {
  platform: NodeJS.Platform
  versions: Readonly<{
    chrome: string
    electron: string
    node: string
  }>
}

declare global {
  interface Window {
    desktopApi: Readonly<DesktopApi>
  }
}

export {}
