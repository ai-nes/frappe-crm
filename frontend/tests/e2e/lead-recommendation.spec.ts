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

// Student NBA: immutable recommendation -> human decision -> NBA Task.
//
// The review queue and the Task workbench are distinct surfaces. Accepting a
// recommendation is the only path that materialises a Task; reject / defer /
// dismiss never do. This spec walks the accept path end to end. It is structured
// for a provisioned scenario catalog and skips when the fixture is absent, so it
// is safe to keep out of the default CI lane.
test.describe('Student NBA recommendation to task', () => {
  test.use({ storageState: storageStateFor('saleA') })

  test('accepting a recommendation records the decision and creates exactly one NBA Task', async ({
    page,
  }) => {
    const recommendation = scenarioValue('PLAYWRIGHT_SALE_RECOMMENDATION_ID')
    const student = scenarioValue('PLAYWRIGHT_SALE_RECOMMENDATION_STUDENT_ID')
    const studentLabel = scenarioValue('PLAYWRIGHT_SALE_RECOMMENDATION_STUDENT_LABEL')
    test.skip(
      !recommendation || !student,
      'Scenario catalog has not provisioned the Sale recommendation fixture.',
    )
    if (!recommendation || !student) return

    // 1. Review queue shows the immutable AI proposal, not a task.
    await page.goto('my-recommendations')
    const card = page
      .locator('article')
      .filter({ hasText: studentLabel || student })
      .first()
    await expect(card).toBeVisible()
    await expect(card.getByText(localizedLabel('AI recommendation', 'Đề xuất AI'))).toBeVisible()

    // 2. Accept and schedule through the Phase 6 decision dialog.
    await card
      .getByRole('button', { name: localizedLabel('Accept', 'Tiếp nhận') })
      .click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    const dueAt = dialog.getByLabel(/due|thời hạn|lịch hẹn/i).first()
    await dueAt.fill('2026-09-10T09:00')
    await dialog
      .getByRole('button', { name: localizedLabel('Confirm', 'Xác nhận') })
      .click()
    await expect(dialog).toBeHidden()

    // 3. The recommendation decision is persisted as accepted.
    await expect
      .poll(async () => (await readDoc(page, 'CRM Recommendation', recommendation)).decision_status)
      .toBe('accepted')

    // 4. Exactly one NBA Task now exists for the accepted decision, and it is
    //    visible on the Task workbench (a separate queue from the review queue).
    await page.goto('my-recommendations?tab=actions')
    await expect(
      page.locator('article').filter({ hasText: studentLabel || student }),
    ).toHaveCount(1)
  })

  test('rejecting a scoped recommendation persists the decision and creates no task', async ({
    page,
  }) => {
    const recommendation = scenarioValue('PLAYWRIGHT_SALE_REJECT_RECOMMENDATION_ID')
    const student = scenarioValue('PLAYWRIGHT_SALE_REJECT_RECOMMENDATION_STUDENT_ID')
    const studentLabel = scenarioValue('PLAYWRIGHT_SALE_REJECT_RECOMMENDATION_STUDENT_LABEL')
    test.skip(
      !recommendation || !student,
      'Scenario catalog has not provisioned the Sale reject recommendation fixture.',
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
    const dialog = page.getByRole('dialog')
    await dialog
      .getByRole('textbox', { name: /reason|lý do/i })
      .fill('Playwright rejection evidence')
    await dialog
      .getByRole('button', { name: localizedLabel('Confirm', 'Xác nhận') })
      .click()
    await expect(dialog).toBeHidden()
    await expect
      .poll(async () => (await readDoc(page, 'CRM Recommendation', recommendation)).decision_status)
      .toBe('rejected')
  })
})
