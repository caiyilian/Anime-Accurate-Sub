// @vitest-environment node
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { projectRootCandidates, pythonCandidates } from './diagnostics'
import { DEFAULT_SETTINGS } from './settings'

describe('diagnostic discovery', () => {
  it('prioritizes explicit settings and environment variables without duplicates', () => {
    const settings = {
      ...DEFAULT_SETTINGS,
      projectRoot: resolve('chosen-root'),
      pythonPath: resolve('python.exe')
    }
    const roots = projectRootCandidates(settings, {
      appPath: resolve('desktop'),
      resourcesPath: resolve('resources'),
      env: { ANIME_ACCURATE_SUB_ROOT: resolve('env-root') }
    })
    expect(roots[0]).toBe(settings.projectRoot)
    expect(roots[1]).toBe(resolve('env-root'))

    const pythons = pythonCandidates(settings, settings.projectRoot, {
      ANIME_ACCURATE_SUB_PYTHON: resolve('env-python.exe'),
      PATH: ''
    })
    expect(pythons.slice(0, 2)).toEqual([settings.pythonPath, resolve('env-python.exe')])
    expect(new Set(pythons).size).toBe(pythons.length)
  })

  it('keeps the packaged backend ahead of development fallbacks', () => {
    const resourcesPath = resolve('packaged-resources')
    const roots = projectRootCandidates(DEFAULT_SETTINGS, {
      appPath: resolve('app.asar'),
      resourcesPath,
      userDataPath: resolve('user-data'),
      env: { PATH: '' }
    })
    expect(roots[0]).toBe(resolve(resourcesPath, 'backend'))
  })
})
