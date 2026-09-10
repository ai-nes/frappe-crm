import { test, expect } from './fixtures/auth'
import {
  fixtureValue,
  localizedLabel,
  readDoc,
  readList,
} from './fixtures/lead-fixture'

test('does not expose conversion for a non-Enrolled Student', async ({
  page,
}) => {
  const student = fixtureValue('PLAYWRIGHT_NON_ENROLLED_STUDENT_ID')
  await page.goto(`crm-students/${encodeURIComponent(student)}#overview`)
  const studentDoc = await readDoc(page, 'CRM Student', student)
  expect(studentDoc.lifecycle_stage).not.toBe('Enrolled')
  const conversion = page.locator('section[aria-label="Student conversion"]')
  // Non-Enrolled state is intentionally not advertised by StudentOverview, so
  // the whole conversion region may be absent. If a staged rollout still
  // renders it, the command must remain unavailable.
  if (await conversion.count()) {
    await expect(conversion).toBeVisible()
    await expect(
      conversion.getByRole('button', {
        name: localizedLabel(
          'Convert to Contact',
          'Chuyển sang hổ sơ tiềm năng',
        ),
      }),
    ).toHaveCount(0)
  }
  await expect
    .poll(
      async () =>
        (await readList(page, 'CRM Student Contact Conversion', { student }))
          .length,
    )
    .toBe(0)
})

test('converts the named Enrolled Student and preserves case history', async ({
  page,
}) => {
  const student = fixtureValue('PLAYWRIGHT_ENROLLED_STUDENT_ID')
  const expectedRevision = fixtureValue(
    'PLAYWRIGHT_ENROLLED_LIFECYCLE_REVISION',
  )
  await page.goto(`crm-students/${encodeURIComponent(student)}#overview`)
  const studentBefore = await readDoc(page, 'CRM Student', student)
  expect(studentBefore.lifecycle_stage).toBe('Enrolled')
  expect(String(studentBefore.lifecycle_revision)).toBe(expectedRevision)
  const existingConversions = await readList(
    page,
    'CRM Student Contact Conversion',
    { student },
    [
      'name',
      'student',
      'student_identity',
      'case_key',
      'contact',
      'command_receipt',
    ],
  )
  if (existingConversions.length) {
    expect(existingConversions).toHaveLength(1)
    expect(existingConversions[0].contact).toBeTruthy()
    expect(existingConversions[0].command_receipt).toBeTruthy()
    return
  }
  const conversion = page.locator('section[aria-label="Student conversion"]')
  await expect(conversion).toBeVisible()
  await conversion
    .getByRole('button', {
      name: localizedLabel('Convert to Contact', 'Chuyển sang hổ sơ tiềm năng'),
    })
    .click()
  const dialog = page.getByRole('dialog').filter({
    has: page.getByRole('button', {
      name: localizedLabel('Convert to Contact', 'Chuyển sang hổ sơ tiềm năng'),
    }),
  })
  await expect(dialog).toBeVisible()
  await dialog
    .getByRole('button', {
      name: localizedLabel('Convert to Contact', 'Chuyển sang hổ sơ tiềm năng'),
    })
    .click()
  await expect
    .poll(
      async () =>
        readList(page, 'CRM Student Contact Conversion', { student }, [
          'name',
          'student',
          'student_identity',
          'case_key',
          'contact',
          'lifecycle_event',
          'command_receipt',
        ]),
      { timeout: 20_000 },
    )
    .toHaveLength(1)
  const conversionRows = await readList(
    page,
    'CRM Student Contact Conversion',
    { student },
    [
      'name',
      'student',
      'student_identity',
      'case_key',
      'contact',
      'lifecycle_event',
      'command_receipt',
    ],
  )
  const contact = conversionRows[0]?.contact as string | undefined
  expect(contact).toBeTruthy()
  const studentDoc = await readDoc(page, 'CRM Student', student)
  expect(studentDoc.lifecycle_stage).toBe('Enrolled')
  expect(String(studentDoc.lifecycle_revision)).toBe(expectedRevision)
  const conversionRecord = conversionRows[0]
  expect(conversionRecord.student).toBe(student)
  expect(conversionRecord.student_identity).toBe(studentDoc.identity)
  expect(conversionRecord.case_key).toBe(studentDoc.case_key)
  expect(conversionRecord.contact).toBe(contact)
  expect(conversionRecord.command_receipt).toBeTruthy()
  const contactDoc = await readDoc(page, 'CRM Contact', contact as string)
  expect(contactDoc.full_name).toBe(studentDoc.student_name)
  expect(contactDoc.student_identity).toBe(studentDoc.identity)
})
