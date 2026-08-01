import { readFile, readdir, stat } from 'node:fs/promises'
import { basename, extname, join, resolve } from 'node:path'

const [releaseArgument = 'release', ...secretArguments] = process.argv.slice(2)
const releaseRoot = resolve(releaseArgument)
const forbiddenNames = /(?:githubtoken|sensenova_apikeys|\.env(?:\.|$)|api[_-]?keys?|^model\.bin$)/i
const forbiddenExtensions = new Set(['.gguf', '.safetensors', '.mp4', '.mkv', '.avi', '.mov'])

async function filesUnder(directory) {
  const result = []
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) result.push(...(await filesUnder(path)))
    else if (entry.isFile()) result.push(path)
  }
  return result
}

const files = await filesUnder(releaseRoot)
const forbiddenPaths = files.filter(
  (path) =>
    forbiddenNames.test(basename(path)) || forbiddenExtensions.has(extname(path).toLowerCase())
)
if (forbiddenPaths.length) {
  throw new Error(
    `Release contains forbidden resources: ${forbiddenPaths.map((path) => basename(path)).join(', ')}`
  )
}

const secrets = []
for (const argument of secretArguments) {
  try {
    const content = await readFile(resolve(argument), 'utf8')
    secrets.push(
      ...content
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line.length >= 12)
    )
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error
  }
}

for (const path of files) {
  const info = await stat(path)
  if (!secrets.length || info.size > 300 * 1024 * 1024) continue
  const bytes = await readFile(path)
  if (secrets.some((secret) => bytes.includes(Buffer.from(secret)))) {
    throw new Error(`Release file contains a configured secret: ${basename(path)}`)
  }
}

console.log(`RELEASE_SECRET_SCAN_OK files=${files.length} secrets=${secrets.length}`)
