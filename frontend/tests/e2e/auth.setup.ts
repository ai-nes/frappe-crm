import { test as setup, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

const expectedSite = process.env.PLAYWRIGHT_EXPECTED_SITE || 'crm.localhost'
const baseURL =
  process.env.PLAYWRIGHT_BASE_URL || 'http://crm.localhost:8000/crm/'

const personas = [
  {
    name: 'saleA',
    username:
      process.env.PLAYWRIGHT_E2E_SALE_USER ||
      process.env.PLAYWRIGHT_E2E_USER ||
      'sale@gmail.com',
    password:
      process.env.PLAYWRIGHT_E2E_SALE_PASSWORD ||
      process.env.PLAYWRIGHT_E2E_PASSWORD,
  },
  {
    name: 'saleB',
    username: process.env.PLAYWRIGHT_E2E_SALE_B_USER || 'sale@gmail.com',
    password:
      process.env.PLAYWRIGHT_E2E_SALE_B_PASSWORD ||
      process.env.PLAYWRIGHT_E2E_PASSWORD,
  },
  {
    name: 'leadSales',
    username:
      process.env.PLAYWRIGHT_E2E_LEAD_SALES_USER || 'leadsale@gmail.com',
    password:
      process.env.PLAYWRIGHT_E2E_LEAD_SALES_PASSWORD ||
      process.env.PLAYWRIGHT_E2E_PASSWORD,
  },
]

setup('authenticate the isolated admissions personas', async ({ browser }) => {
  if (process.env.PLAYWRIGHT_E2E_ENABLED !== '1') {
    throw new Error(
      'Set PLAYWRIGHT_E2E_ENABLED=1 only on a disposable E2E site.',
    )
  }

  if (personas.some(({ password }) => !password)) {
    throw new Error(
      'Set PLAYWRIGHT_E2E_PASSWORD or per-persona Playwright passwords at runtime.',
    )
  }

  await fs.mkdir(path.resolve('playwright/.auth'), { recursive: true })
  for (const persona of personas) {
    await setup.step(`authenticate ${persona.name}`, async () => {
      const context = await browser.newContext({ baseURL })
      const page = await context.newPage()
      await page.goto('/login')
      await page.locator('#email').fill(persona.username)
      await page.locator('#password').fill(persona.password as string)
      await page.locator('#login-btn').click()
      await page.waitForURL(/\/crm(?:\/|$)/)

      const site = await page.evaluate(() => window.site_name)
      expect(
        site,
        'authenticated browser must report the expected Frappe site',
      ).toBe(expectedSite)
      await expect(page).toHaveURL(/\/crm(?:\/|$)/)
      await context.storageState({
        path: path.resolve(`playwright/.auth/${persona.name}.json`),
      })
      await context.close()
    })
  }
  // Keep the legacy default state for existing specs that do not override it.
  await fs.copyFile(
    path.resolve('playwright/.auth/saleA.json'),
    path.resolve('playwright/.auth/sale.json'),
  )
})
