import { test, expect } from './fixtures/auth'
import { fixtureValue, localizedLabel, readDoc } from './fixtures/lead-fixture'
import { storageStateFor } from './fixtures/personas'

function scenarioValue(key: string) {
  try {
    return fixtureValue(key)
  } catch {
    return null
  }
}

test.describe('Sale recommendation inbox', () => {
  test.use({ storageState: storageStateFor('saleA') })

  test('rejects a scoped recommendation with a reason and refreshes persisted state', async ({
    page,
  }) => {
    const recommendation = scenarioValue('PLAYWRIGHT_SALE_RECOMMENDATION_ID')
    const student = scenarioValue('PLAYWRIGHT_SALE_RECOMMENDATION_STUDENT_ID')
    const studentLabel = scenarioValue(
      'PLAYWRIGHT_SALE_RECOMMENDATION_STUDENT_LABEL',
    )
    test.skip(
      !recommendation || !student,
      'Scenario catalog has not provisioned the Sale recommendation fixture.',
    )
    if (!recommendation || !student) return

    await page.goto('my-recommendations')
    const card = page
      .locator('article')
      .filter({ hasText: studentLabel || student })
      .first()
    await expect(card).toBeVisible()
    await card
      .getByRole('button', { name: localizedLabel('Reject', 'Từ chối') })
      .click()
    const dialog = page.getByRole('dialog', {
      name: /reject recommendation|từ chối đề xuất/i,
    })
    await dialog
      .getByRole('textbox', {
        name: /rejection reason|lý do từ chối/i,
      })
      .fill('Playwright rejection evidence')
    await dialog
      .getByRole('button', { name: localizedLabel('Reject', 'Từ chối') })
      .click()
    await expect(dialog).toBeHidden()
    await expect
      .poll(
        async () =>
          (await readDoc(page, 'CRM Recommendation', recommendation)).status,
      )
      .toBe('rejected')
  })
})
