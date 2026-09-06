import { test, expect } from './fixtures/auth'
import { fillLink, readDoc, readList } from './fixtures/lead-fixture'

const managerUser = process.env.PLAYWRIGHT_ASSIGNMENT_MANAGER_USER
const managerPassword = process.env.PLAYWRIGHT_ASSIGNMENT_MANAGER_PASSWORD
const assignmentSaleUser = process.env.PLAYWRIGHT_ASSIGNMENT_SALE_USER
const assignmentSalePassword = process.env.PLAYWRIGHT_ASSIGNMENT_SALE_PASSWORD
const runId = process.env.E2E_RUN_ID

async function signIn(
  page: import('@playwright/test').Page,
  username: string,
  password: string,
) {
  await page.goto('/login')
  await page.locator('#email').fill(username)
  await page.locator('#password').fill(password)
  await page.locator('#login-btn').click()
  await page.waitForURL(/\/crm(?:\/|$)/)
}

test.describe('Assignment setup and routing journey', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(
      !managerUser ||
        !managerPassword ||
        !assignmentSaleUser ||
        !assignmentSalePassword ||
        !runId,
      'Set manager/sale credentials and E2E_RUN_ID for the guarded local journey.',
    )
    await signIn(page, managerUser as string, managerPassword as string)
  })

  test('manager reviews the read-only tree, follows setup steps, then routes a new Student', async ({
    page,
    browser,
  }) => {
    await page.goto('/crm/assignment-overview')
    await expect(page.getByRole('heading', { name: /Sơ đồ phân bổ/i })).toBeVisible()
    await expect(page.getByTestId('assignment-overview-table')).toContainText(
      'FPTU Ho Chi Minh Campus',
    )

    // The overview opens at the first useful level. Expand one địa bàn before
    // selecting a school so the journey follows the same progressive-disclosure UX.
    await page.getByRole('button', { name: /mở đến zone/i }).click()
    const firstZoneToggle = page
      .locator('[data-testid="expand-assignment-node"][data-level="zone"]')
      .first()
    await expect(firstZoneToggle).toBeVisible()
    await firstZoneToggle.click()
    await expect(page.getByTestId(/select-school-/)).toHaveCount(0)

    await expect(page.getByTestId('open-assignment-setup-drawer')).toBeVisible()
    await page.getByTestId('open-assignment-setup-drawer').click()
    const setupDrawer = page.getByRole('dialog', { name: /các bước setup/i })
    await expect(setupDrawer).toBeVisible()
    await expect(setupDrawer.getByTestId('assignment-setup-guide')).toBeVisible()
    await setupDrawer.getByTestId('assignment-setup-step-policy').click()
    await expect(setupDrawer).toBeHidden()
    await expect(page.getByRole('tab', { name: /cách chia lead/i })).toHaveAttribute(
      'aria-selected',
      'true',
    )

    await page.getByRole('tab', { name: /thiết lập/i }).click()
    await expect(page.getByTestId('assignment-setup-panel')).toBeVisible()
    await expect(page.getByTestId('assignment-setup-guide')).toBeHidden()

    await page.getByRole('tab', { name: /kiểm tra/i }).click()
    const readinessActions = page.locator('[data-testid^="assignment-actions-"]').first()
    await expect(readinessActions).toBeVisible()
    const readinessGeometry = await readinessActions.evaluate((actions) => {
      const row = actions.closest('tr')
      const issueCell = row?.children[3]
      return {
        issueRight: issueCell?.getBoundingClientRect().right ?? 0,
        actionsLeft: actions.getBoundingClientRect().left,
      }
    })
    expect(readinessGeometry.issueRight).toBeLessThanOrEqual(
      readinessGeometry.actionsLeft,
    )

    const saleContext = await browser.newContext({
      baseURL:
        process.env.PLAYWRIGHT_BASE_URL || 'http://crm.localhost:8000/crm/',
    })
    const salePage = await saleContext.newPage()
    await signIn(
      salePage,
      assignmentSaleUser as string,
      assignmentSalePassword as string,
    )
    await salePage.goto('/crm/crm-students/view/list')
    await salePage
      .getByRole('button', { name: /new student|tạo học sinh/i })
      .click()
    const intake = salePage
      .getByRole('dialog')
      .filter({ has: salePage.locator('[data-fieldname="student_name"]') })
    await expect(intake).toBeVisible()
    const studentKey = `${runId}-${Date.now()}`
    await intake
      .locator('[data-fieldname="student_name"] input')
      .fill(`Playwright Student ${studentKey}`)
    await intake
      .locator('[data-fieldname="phone"] input')
      .fill(`098${String(Date.now()).slice(-7)}`)

    await intake
      .locator('[data-fieldname="email"] input')
      .fill(`${studentKey.toLowerCase()}@example.test`)
    const year = (
      await readList(salePage, 'CRM Admission Year', {}, ['name'])
    )[0]
    expect(year?.name).toBeTruthy()
    await fillLink(salePage, 'admission_year', year.name as string)
    await intake.getByRole('button', { name: /^(tạo|create)$/i }).click()
    await expect(intake).toBeHidden()

    await expect(salePage).toHaveURL(/\/crm\/crm-students\/(?!view\/)/)
    const studentId = (await salePage.url())
      .split('/crm-students/')[1]
      .split('#')[0]
    await expect
      .poll(
        async () =>
          (
            await readDoc(
              salePage,
              'CRM Student',
              decodeURIComponent(studentId),
            )
          ).owner_staff,
        { timeout: 20_000 },
      )
      .toBeTruthy()
    const owner = (
      await readDoc(salePage, 'CRM Student', decodeURIComponent(studentId))
    ).owner_staff
    expect(owner).toBeTruthy()
    await expect(
      salePage.getByText(/current assignment|phân công hiện tại/i).first(),
    ).toBeVisible()
    await saleContext.close()
  })
})
