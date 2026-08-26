import { test, expect } from './fixtures/auth'
import {
  fixtureValue,
  localizedLabel,
  readOwnership,
} from './fixtures/lead-fixture'
import { storageStateFor } from './fixtures/personas'

function scenarioValue(key: string) {
  try {
    return fixtureValue(key)
  } catch {
    return null
  }
}

test.describe('Sale ownership boundary', () => {
  test.use({ storageState: storageStateFor('saleA') })

  test('does not expose reassignment to Sale', async ({
    page,
  }) => {
    const student = scenarioValue('PLAYWRIGHT_SALE_OWNERSHIP_STUDENT_ID')
    test.skip(!student, 'Scenario catalog has not provisioned the Sale ownership fixture.')
    if (!student) return

    await page.goto(`crm-students/${encodeURIComponent(student)}#overview`)
    await expect(
      page.getByRole('button', {
        name: localizedLabel('Change ownership', 'Đổi người phụ trách'),
      }),
    ).toHaveCount(0)
  })
})

test.describe('Lead Sales ownership journey', () => {
  test.use({ storageState: storageStateFor('leadSales') })

  test('changes ownership through the Student screen and persists the revision', async ({
    page,
  }) => {
    const student = scenarioValue('PLAYWRIGHT_LEAD_SALES_STUDENT_ID')
    const target = scenarioValue('PLAYWRIGHT_LEAD_SALES_OWNERSHIP_TARGET_POOL_ID')
    test.skip(!student || !target, 'Scenario catalog has not provisioned the Lead Sales ownership fixture.')
    if (!student || !target) return

    await page.goto(`crm-students/${encodeURIComponent(student)}#overview`)
    await expect(
      page.getByRole('button', {
        name: localizedLabel('Change ownership', 'Đổi người phụ trách'),
      }),
    ).toBeVisible()
    const before = await readOwnership(page, student)
    await page.getByRole('button', {
      name: localizedLabel('Change ownership', 'Đổi người phụ trách'),
    }).click()
    const dialog = page.getByRole('dialog', {
      name: /change student ownership|đổi người phụ trách/i,
    })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('combobox').nth(1).click()
    await page.getByRole('option').filter({ hasText: target }).first().click()
    await dialog
      .getByRole('textbox', { name: /reason|lý do/i })
      .fill('Playwright Lead Sales ownership coverage')
    await dialog.getByRole('button', {
      name: localizedLabel('Save ownership', 'Lưu phân công'),
    }).click()
    await expect(dialog).toBeHidden()
    await expect
      .poll(async () => Number((await readOwnership(page, student)).revision))
      .toBeGreaterThan(Number(before.revision))
  })
})
