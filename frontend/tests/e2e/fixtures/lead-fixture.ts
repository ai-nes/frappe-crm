import fs from 'node:fs'
import { expect } from '@playwright/test'
import { runContext } from './run-context'

type FixtureManifest = Record<string, string | undefined>

async function readApi(
  page: import('@playwright/test').Page,
  path: string,
  params: Record<string, string>,
) {
  const result = await page.evaluate(
    async ({ path: requestPath, params: requestParams }) => {
      const url = new URL(requestPath, window.location.origin)
      Object.entries(requestParams).forEach(([key, value]) =>
        url.searchParams.set(key, value),
      )
      const response = await fetch(url)
      const rawBody = await response.text()
      let body: unknown
      try {
        body = JSON.parse(rawBody)
      } catch {
        body = rawBody
      }
      return {
        ok: response.ok,
        status: response.status,
        body,
      }
    },
    { path, params },
  )
  expect(
    result.ok,
    `${path} returned HTTP ${result.status}: ${JSON.stringify(result.body)}`,
  ).toBeTruthy()
  expect(
    result.body && typeof result.body === 'object' && !('exc' in result.body),
    `${path} returned a Frappe error: ${JSON.stringify(result.body)}`,
  ).toBeTruthy()
  return (result.body as { message?: unknown }).message
}

/** Match labels rendered by either the English or Vietnamese site catalogue. */
export function localizedLabel(...labels: string[]): RegExp {
  const escaped = labels.map((label) =>
    label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
  )
  return new RegExp(`^(?:${escaped.join('|')})$`, 'i')
}

function manifest(): FixtureManifest {
  if (process.env.E2E_RUN_ID) return runContext().manifest
  const file = process.env.PLAYWRIGHT_FIXTURE_MANIFEST
  if (!file) return {}
  return JSON.parse(fs.readFileSync(file, 'utf8')) as FixtureManifest
}

export function fixtureValue(key: string): string {
  const value = manifest()[key] || process.env[key]
  if (!value) {
    throw new Error(
      `Missing ${key}; provision the isolated fixture before running Playwright.`,
    )
  }
  return value
}

export function runSuffix(): string {
  const runId = process.env.E2E_RUN_ID
  return runId
    ? `PW-${runId}-${Date.now()}-${process.pid}`
    : `PW-${Date.now()}-${process.pid}`
}

export async function readDoc(
  page: import('@playwright/test').Page,
  doctype: string,
  name: string,
) {
  return readApi(page, '/api/method/frappe.client.get', {
    doctype,
    name,
  }) as Promise<Record<string, unknown>>
}

export async function readList(
  page: import('@playwright/test').Page,
  doctype: string,
  filters: Record<string, string>,
  fields: string[] = ['name'],
) {
  return readApi(page, '/api/method/frappe.client.get_list', {
    doctype,
    filters: JSON.stringify(filters),
    fields: JSON.stringify(fields),
  }) as Promise<Array<Record<string, unknown>>>
}

export async function readOwnership(
  page: import('@playwright/test').Page,
  student: string,
) {
  return readApi(
    page,
    '/api/method/crm.api.student_ownership.get_student_ownership',
    { student },
  ) as Promise<Record<string, unknown>>
}

export async function readOwnershipTargets(
  page: import('@playwright/test').Page,
  student: string,
) {
  return readApi(
    page,
    '/api/method/crm.api.student_ownership.get_eligible_ownership_targets',
    { student },
  ) as Promise<{
    owners?: Array<{ name: string; label?: string }>
    pools?: Array<{ name: string; label?: string }>
  }>
}

export async function readSlaStatus(
  page: import('@playwright/test').Page,
  student: string,
) {
  return readApi(
    page,
    '/api/method/crm.api.student_sla.get_student_sla_status',
    { student },
  ) as Promise<Record<string, unknown>>
}

export async function readStudentContext(
  page: import('@playwright/test').Page,
  student: string,
) {
  return readApi(
    page,
    '/api/method/crm.api.student_engagement.get_student_context',
    { student, history_limit: '50' },
  ) as Promise<Record<string, unknown>>
}

export async function waitForDoc(
  page: import('@playwright/test').Page,
  doctype: string,
  name: string,
  predicate: (doc: Record<string, unknown>) => boolean,
) {
  await expect
    .poll(async () => predicate(await readDoc(page, doctype, name)), {
      timeout: 20_000,
    })
    .toBeTruthy()
  return readDoc(page, doctype, name)
}

export async function fillLink(
  page: import('@playwright/test').Page,
  fieldname: string,
  value: string,
) {
  const field = page.locator(`[data-fieldname="${fieldname}"]`)
  const input = field.locator('input').first()
  if (await input.count()) {
    await input.fill(value)
  } else {
    await field.locator('button').first().click()
    const search = page
      .locator('input[placeholder="Tìm kiếm"], input[placeholder="Search"]')
      .last()
    if (await search.count()) await search.fill(value)
  }
  const option = page.getByRole('option').filter({ hasText: value }).first()
  if (await option.count()) {
    await expect(option).toBeVisible()
    await option.click()
    return
  }
  const textOption = page.getByText(value, { exact: true }).last()
  await expect(textOption).toBeVisible()
  await textOption.click()
}
