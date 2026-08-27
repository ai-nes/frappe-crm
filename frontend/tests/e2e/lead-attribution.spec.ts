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

test.describe('Lead Sales attribution visibility', () => {
  test.use({ storageState: storageStateFor('leadSales') })

  test('shows only the read projection when attribution management is not granted', async ({
    page,
  }) => {
    const event = scenarioValue('PLAYWRIGHT_LEAD_SALES_EVENT_ID')
    test.skip(
      !event,
      'Scenario catalog has not provisioned a Lead Sales-readable Event fixture.',
    )
    if (!event) return

    await page.goto(`crm-events/${encodeURIComponent(event)}#overview`)
    const panel = page.locator('section[aria-label="Marketing attribution"]')
    await expect(panel).toBeVisible()
    await expect(
      panel.getByRole('button', {
        name: localizedLabel('Record evidence', 'Ghi nhận bằng chứng'),
      }),
    ).toHaveCount(0)
  })
})
