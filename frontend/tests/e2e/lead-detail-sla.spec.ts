import { test, expect } from './fixtures/auth'
import {
  fixtureValue,
  localizedLabel,
  readDoc,
  readList,
  readOwnership,
} from './fixtures/lead-fixture'

// Ownership changes are a Lead Sales capability.  Keep the positive mutation
// journey on that persona; Sale remains covered by the explicit denial specs.
test.use({ storageState: 'playwright/.auth/leadSales.json' })

test('shows ownership and records an outcome against the named first-response SLA', async ({
  page,
}) => {
  const student = fixtureValue('PLAYWRIGHT_DETAIL_STUDENT_ID')
  await page.goto(`crm-students/${encodeURIComponent(student)}#overview`)
  await expect(
    page.locator('section[aria-label="Initial-response SLA"]'),
  ).toBeVisible()
  await expect(
    page.getByRole('button', {
      name: localizedLabel('Change ownership', 'Đổi người phụ trách'),
    }),
  ).toBeVisible()

  const ownership = await readOwnership(page, student)
  expect(ownership.student).toBe(student)

  // Record outcome is exposed from the Interactions tab, not the Overview panel.
  await page
    .getByRole('tab', { name: localizedLabel('Interactions', 'Tương tác') })
    .click()
  await page
    .getByRole('button', {
      name: localizedLabel('Record outcome', 'Ghi nhận kết quả'),
    })
    .click()
  const dialog = page.getByRole('dialog').filter({
    hasText: /Record student outcome|Ghi nhận kết quả/i,
  })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('combobox').first().click()
  await page
    .getByText(/connected|đã liên hệ/i)
    .last()
    .click()
  await dialog.getByRole('combobox').nth(1).click()
  await page
    .getByText(/task|công việc/i)
    .last()
    .click()
  const textboxes = dialog.getByRole('textbox')
  await textboxes.nth(0).fill('Playwright follow-up')
  await textboxes
    .nth(1)
    .fill(
      process.env.PLAYWRIGHT_OUTCOME_ASSIGNEE ||
        process.env.PLAYWRIGHT_E2E_USER ||
        'Administrator',
    )
  await dialog.locator('input[type="datetime-local"]').fill('2030-01-01T09:00')
  await dialog
    .getByRole('button', {
      name: localizedLabel('Record outcome', 'Ghi nhận kết quả'),
    })
    .click()
  await expect(dialog).toBeHidden()

  const slaAttempt = fixtureValue('PLAYWRIGHT_DETAIL_SLA_ATTEMPT_ID')
  const slaDoc = await readDoc(page, 'CRM Student SLA Attempt', slaAttempt)
  expect(slaDoc.student).toBe(student)
  const outcomes = await readList(page, 'CRM Student Outcome', { student }, [
    'name',
    'student',
    'outcome_code',
    'interaction',
  ])
  expect(outcomes.length).toBeGreaterThan(0)
  expect(outcomes.at(-1)?.student).toBe(student)
  expect(outcomes.at(-1)?.outcome_code).toBe('connected')
  const studentDoc = await readDoc(page, 'CRM Student', student)
  expect(studentDoc.name).toBe(student)
})
