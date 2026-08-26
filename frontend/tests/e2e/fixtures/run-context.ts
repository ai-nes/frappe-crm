import fs from 'node:fs'
import path from 'node:path'

export type RunManifest = Record<string, string | undefined>

const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{5,63}$/

export function runContext(): {
  runId: string
  manifestPath: string
  manifest: RunManifest
} {
  const runId = process.env.E2E_RUN_ID
  if (!runId || !RUN_ID_PATTERN.test(runId)) {
    throw new Error(
      'E2E_RUN_ID is required and must be a safe 6-64 character namespace.',
    )
  }
  const manifestPath =
    process.env.PLAYWRIGHT_FIXTURE_MANIFEST ||
    path.resolve(`playwright-fixture.${runId}.json`)
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Run manifest is missing: ${manifestPath}`)
  }
  const manifest = JSON.parse(
    fs.readFileSync(manifestPath, 'utf8'),
  ) as RunManifest
  if (manifest.E2E_RUN_ID !== runId) {
    throw new Error(
      `Manifest run mismatch: expected ${runId}, received ${manifest.E2E_RUN_ID || 'none'}.`,
    )
  }
  return { runId, manifestPath, manifest }
}

export function assertRunScoped(value: string, field: string): string {
  if (!value.includes(runContext().runId)) {
    throw new Error(`${field} is not scoped to E2E_RUN_ID.`)
  }
  return value
}
