import { test, expect } from './fixtures/auth'
import {
  fillLink,
  fixtureValue,
  localizedLabel,
  readDoc,
  readList,
  runSuffix,
} from './fixtures/lead-fixture'

// Intake creates an unassigned/team-pool case before routing.  Lead Sales has
// the team-pool read scope needed to verify the newly-created Student while
// Sale's own-assigned scope is covered by the seeded journeys.
test.use({ storageState: 'playwright/.auth/leadSales.json' })

test.describe('canonical Student intake', () => {
  test('creates a Student through the intake dialog', async ({ page }) => {
    await page.goto('crm-students/view/list?stage=intake')
    await page
      .getByRole('button', {
        name: localizedLabel('New student', 'Tạo học sinh'),
      })
      .click()
    const dialog = page
      .getByRole('dialog')
      .filter({ has: page.locator('[data-fieldname="student_name"]') })
    const suffix = runSuffix()
    await dialog
      .locator('[data-fieldname="student_name"] input')
      .fill(`Playwright ${suffix}`)
    await dialog
      .locator('[data-fieldname="phone"] input')
      .fill(`090${String(Date.now()).slice(-7)}`)
    await dialog
      .locator('[data-fieldname="email"] input')
      .fill(`${suffix.toLowerCase()}@example.test`)
    await dialog
      .getByRole('button', { name: /Identity and assignment/i })
      .click()
    await fillLink(
      page,
      'owning_team',
      fixtureValue('PLAYWRIGHT_INITIAL_POOL_ID'),
    )
    await fillLink(
      page,
      'branch',
      process.env.PLAYWRIGHT_CAMPUS ||
        fixtureValue('PLAYWRIGHT_INITIAL_CAMPUS_ID'),
    )
    await fillLink(
      page,
      'admission_year',
      process.env.PLAYWRIGHT_ADMISSION_YEAR || '2026',
    )
    await dialog
      .getByRole('button', { name: localizedLabel('Create', 'Tạo') })
      .click()
    await expect(dialog).toBeHidden()
    await expect
      .poll(
        () =>
          readList(
            page,
            'CRM Student',
            { student_name: `Playwright ${suffix}` },
            ['name', 'student_name'],
          ),
        { timeout: 20_000 },
      )
      .toHaveLength(1)
    const createdStudents = await readList(
      page,
      'CRM Student',
      { student_name: `Playwright ${suffix}` },
      ['name', 'student_name'],
    )
    const createdStudent = createdStudents[0]?.name as string | undefined
    expect(createdStudent).toBeTruthy()
    await page.goto(
      `crm-students/${encodeURIComponent(createdStudent as string)}#overview`,
    )
    await expect(
      page.locator('section[aria-label="Student summary"]'),
    ).toBeVisible()

    const studentDoc = await readDoc(
      page,
      'CRM Student',
      createdStudent as string,
    )
    expect(studentDoc.student_name).toContain('Playwright')
    expect(studentDoc.lifecycle_stage).toBe('Lead')
    expect(studentDoc.enrollment_status).toBe('Mới')
    expect(studentDoc.identity).toBeTruthy()
    expect(studentDoc.case_key).toBeTruthy()
    expect(studentDoc.branch).toBeTruthy()
  })

  test('blocks a payload without phone or email before submission', async ({
    page,
  }) => {
    await page.goto('crm-students/view/list?stage=intake')
    await page
      .getByRole('button', {
        name: localizedLabel('New student', 'Tạo học sinh'),
      })
      .click()
    const suffix = runSuffix()
    const studentName = `Invalid ${suffix}`
    const dialog = page
      .getByRole('dialog')
      .filter({ has: page.locator('[data-fieldname="student_name"]') })
    await dialog
      .locator('[data-fieldname="student_name"] input')
      .fill(studentName)
    await fillLink(
      page,
      'branch',
      process.env.PLAYWRIGHT_CAMPUS ||
        fixtureValue('PLAYWRIGHT_INITIAL_CAMPUS_ID'),
    )
    await fillLink(
      page,
      'admission_year',
      process.env.PLAYWRIGHT_ADMISSION_YEAR || '2026',
    )
    await expect(
      dialog.getByRole('button', { name: localizedLabel('Create', 'Tạo') }),
    ).toBeDisabled()
    expect(
      await readList(page, 'CRM Student', { student_name: studentName }),
    ).toHaveLength(0)
  })
})
