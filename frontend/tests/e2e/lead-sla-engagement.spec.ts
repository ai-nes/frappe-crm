import { test, expect } from './fixtures/auth'
import {
  fixtureValue,
  localizedLabel,
  readList,
  readSlaStatus,
} from './fixtures/lead-fixture'
import { storageStateFor } from './fixtures/personas'

function scenarioValue(key: string) {
  try {
    return fixtureValue(key)
  } catch {
    return null
  }
}

test.describe('Sale SLA and engagement journey', () => {
  test.use({ storageState: storageStateFor('saleA') })

  test('shows the assigned SLA and records an outcome through the interaction UI', async ({
    page,
  }) => {
    const student = scenarioValue('PLAYWRIGHT_SLA_ENGAGEMENT_STUDENT_ID')
    test.skip(
      !student,
      'Scenario catalog has not provisioned the Sale SLA-engagement fixture.',
    )
    if (!student) return

    await page.goto(`crm-students/${encodeURIComponent(student)}#overview`)
    await expect(
      page.locator('section[aria-label="Initial-response SLA"]'),
    ).toBeVisible()
    await expect(
      page.getByRole('tab', {
        name: localizedLabel('Interactions', 'Tương tác'),
      }),
    ).toBeVisible()
    await page
      .getByRole('tab', { name: localizedLabel('Interactions', 'Tương tác') })
      .click()
    await page
      .getByRole('button', {
        name: localizedLabel('Record outcome', 'Ghi nhận kết quả'),
      })
      .click()
    const dialog = page.getByRole('dialog', {
      name: /record student outcome|ghi nhận kết quả/i,
    })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('combobox').first().click()
    await page.getByText(/connected|đã liên hệ/i).last().click()
    await dialog.getByRole('combobox').nth(1).click()
    await page.getByText(/task|công việc/i).last().click()
    const textboxes = dialog.getByRole('textbox')
    await textboxes.nth(0).fill('Playwright Sale follow-up')
    await textboxes.nth(1).fill(process.env.PLAYWRIGHT_E2E_USER || 'Administrator')
    await dialog.locator('input[type="datetime-local"]').fill('2030-01-01T09:00')
    await dialog
      .getByRole('button', {
        name: localizedLabel('Record outcome', 'Ghi nhận kết quả'),
      })
      .click()
    await expect(dialog).toBeHidden()
    await expect
      .poll(
        async () =>
          (await readList(page, 'CRM Student Outcome', { student }, ['name']))
            .length,
      )
      .toBeGreaterThan(0)
    expect(await readSlaStatus(page, student)).toBeTruthy()
  })
})
