import { test, expect } from './fixtures/auth'
import { fixtureValue } from './fixtures/lead-fixture'
import { storageStateFor } from './fixtures/personas'

function scenarioValue(key: string) {
  try {
    return fixtureValue(key)
  } catch {
    return null
  }
}

test.describe('Sale critical-admission audit visibility', () => {
  test.use({ storageState: storageStateFor('saleA') })

  test('renders the scoped audit timeline without a governance mutation control', async ({
    page,
  }) => {
    const student = scenarioValue('PLAYWRIGHT_SALE_AUDIT_STUDENT_ID')
    test.skip(
      !student,
      'Scenario catalog has not provisioned a Sale-readable audit fixture.',
    )
    if (!student) return

    await page.goto(`crm-students/${encodeURIComponent(student)}#overview`)
    const timeline = page.locator(
      'section[aria-label="Critical admission history"]',
    )
    await expect(timeline).toBeVisible()
    await expect(
      timeline.getByRole('button', { name: /approve|reject|break-glass/i }),
    ).toHaveCount(0)
  })
})
