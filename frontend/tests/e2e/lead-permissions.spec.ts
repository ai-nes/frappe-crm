import { test, expect } from './fixtures/auth'
import { fixtureValue, localizedLabel } from './fixtures/lead-fixture'
import { storageStateFor } from './fixtures/personas'

function scenarioValue(key: string) {
  try {
    return fixtureValue(key)
  } catch {
    return null
  }
}

test.describe('Lead Sales direct-route boundary', () => {
  test.use({ storageState: storageStateFor('leadSales') })

  test('does not reveal command controls for a forbidden cross-scope Student URL', async ({
    page,
  }) => {
    const student = scenarioValue('PLAYWRIGHT_LEAD_SALES_FORBIDDEN_STUDENT_ID')
    test.skip(
      !student,
      'Scenario catalog has not provisioned a cross-scope Student fixture.',
    )
    if (!student) return

    await page.goto(`crm-students/${encodeURIComponent(student)}#overview`)
    await expect(
      page.getByRole('button', {
        name: localizedLabel('Change ownership', 'Đổi người phụ trách'),
      }),
    ).toHaveCount(0)
    await expect(
      page.getByRole('button', {
        name: localizedLabel('Record outcome', 'Ghi nhận kết quả'),
      }),
    ).toHaveCount(0)
  })
})
