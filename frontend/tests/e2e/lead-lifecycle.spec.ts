import { test, expect } from './fixtures/auth'
import {
  fixtureValue,
  localizedLabel,
  readDoc,
  readStudentContext,
  waitForDoc,
} from './fixtures/lead-fixture'

test('records a forward lifecycle transition using seeded evidence', async ({
  page,
}) => {
  const student = fixtureValue('PLAYWRIGHT_LIFECYCLE_STUDENT_ID')
  const target = process.env.PLAYWRIGHT_LIFECYCLE_TARGET || 'Applicant'
  await page.goto(`crm-students/${encodeURIComponent(student)}#overview`)
  const before = await readDoc(page, 'CRM Student', student)
  if (before.lifecycle_stage === target) return
  expect(before.lifecycle_stage).toBe('Lead')
  const lifecycle = page.locator(
    'section[aria-labelledby="student-overview-current-state"]',
  )
  await expect(lifecycle).toBeVisible()
  // The sidebar also contains an "Enrolled Students" button.  Scope the
  // action to the page header so the lifecycle command cannot navigate away
  // to a list route by matching an unrelated navigation label.
  await page
    .locator('header')
    .getByRole('button')
    .filter({ hasText: /Mới|Lead|MQL|Applicant|Enrolled|Thí sinh|Đã nhập học/ })
    .first()
    .click()
  const dialog = page.getByRole('dialog').filter({
    hasText: /Change student lifecycle|Chuyển giai đoạn tuyển sinh/i,
  })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('combobox').first().click()
  await page
    .getByRole('option')
    .filter({ hasText: new RegExp(target, 'i') })
    .first()
    .click()
  const comboboxes = dialog.getByRole('combobox')
  if ((await comboboxes.count()) > 1) {
    await comboboxes.nth(1).click()
    await page
      .getByRole('option')
      .filter({ hasText: /qualified|đủ điều kiện/i })
      .first()
      .click()
    await dialog
      .locator('textarea')
      .first()
      .fill(
        [
          fixtureValue('PLAYWRIGHT_LIFECYCLE_EVIDENCE_REF'),
          fixtureValue('PLAYWRIGHT_LIFECYCLE_DOCUMENT_REF'),
          fixtureValue('PLAYWRIGHT_LIFECYCLE_OUTCOME_REF'),
        ].join('\n'),
      )
  }
  await dialog
    .locator('textarea')
    .last()
    .fill('Playwright evidence-backed transition')
  await dialog
    .getByRole('button', {
      name: localizedLabel('Record transition', 'Ghi nhận chuyển giai đoạn'),
    })
    .click()
  await expect(dialog).toBeHidden()
  const doc = await waitForDoc(
    page,
    'CRM Student',
    student,
    (value) => value.lifecycle_stage === target,
  )
  expect(doc.lifecycle_stage).toBe(target)
  const context = await readStudentContext(page, student)
  const history = Array.isArray(context.history) ? context.history : []
  const transition = history.find(
    (event) => (event as Record<string, unknown>).to_stage === target,
  ) as Record<string, unknown> | undefined
  expect(transition).toBeTruthy()
  expect(Array.isArray(transition?.evidence)).toBeTruthy()
  const lifecycleEventName = transition?.name
  expect(lifecycleEventName).toBeTruthy()
  const lifecycleEvent = await readDoc(
    page,
    'CRM Student Lifecycle Event',
    lifecycleEventName as string,
  )
  expect(lifecycleEvent.command_receipt).toBeTruthy()
  const evidenceValue = lifecycleEvent.evidence_references
  const persistedEvidence = (
    typeof evidenceValue === 'string'
      ? JSON.parse(evidenceValue)
      : evidenceValue
  ) as Array<Record<string, unknown>>
  for (const reference of [
    fixtureValue('PLAYWRIGHT_LIFECYCLE_EVIDENCE_REF'),
    fixtureValue('PLAYWRIGHT_LIFECYCLE_DOCUMENT_REF'),
    fixtureValue('PLAYWRIGHT_LIFECYCLE_OUTCOME_REF'),
  ]) {
    const [, doctype, name] = reference.split(':')
    expect(
      persistedEvidence.some(
        (item) => item.doctype === doctype && item.name === name,
      ),
    ).toBeTruthy()
  }
})
