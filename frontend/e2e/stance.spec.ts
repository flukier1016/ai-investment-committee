/**
 * 防线：L3 五档立场必须逐桶直出后端 DecisionRecord，不能由前端按权重差重算；
 * 同时守住中英翻译与移动端无横向溢出。
 */
import { expect, test } from '@playwright/test'

interface StanceBundle {
  bucket_stances: Record<string, string>
}

test('L3 逐桶展示后端五档立场并支持中英移动端', async ({ page }) => {
  const decisionResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/decisions/run')
    && response.request().method() === 'POST'
    && response.ok())

  await page.goto('/trace')
  const bundle = await (await decisionResponse).json() as StanceBundle
  await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })

  const stances = Object.entries(bundle.bucket_stances)
  expect(stances).toHaveLength(7)
  await expect(page.locator('#weights .stance-badge')).toHaveCount(7)

  for (const [bucketId, stance] of stances) {
    const row = page.locator(`#weights .weight-row[data-bucket="${bucketId}"]`)
    await expect(row).toHaveCount(1)
    await expect(row.locator('.stance-badge')).toHaveText(stance)
  }

  await expect(page.locator('#weights .weight-row[data-bucket="commodity"] .stance-badge')).toHaveText('显著超配')
  await expect(page.locator('#weights .weight-row[data-bucket="fx"] .stance-badge')).toHaveText('显著低配')

  await page.locator('.pref-btn').nth(1).click()
  await expect(page.locator('#weights .weight-row[data-bucket="commodity"] .stance-badge')).toHaveText('Strong Overweight')
  await expect(page.locator('#weights .weight-row[data-bucket="fx"] .stance-badge')).toHaveText('Strong Underweight')

  await page.setViewportSize({ width: 390, height: 844 })
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(2)

  await page.evaluate(() => localStorage.clear())
})

test('立场徽章语义服从后端枚举而非前端权重差', async ({ page }) => {
  await page.route('**/api/decisions/run', async (route) => {
    const response = await route.fetch()
    const bundle = await response.json() as StanceBundle
    // 基线中国股票 delta 为正，故意把后端立场置为显著低配，
    // 以证明徽章不会在浏览器里用 target - prior 重判方向。
    bundle.bucket_stances.cn_equity = '显著低配'
    await route.fulfill({ response, json: bundle })
  })

  await page.goto('/trace')
  await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
  const row = page.locator('#weights .weight-row[data-bucket="cn_equity"]')
  await expect(row.locator('.weight-numbers span').nth(1)).toContainText('+')
  await expect(row.locator('.stance-badge')).toHaveText('显著低配')
  await expect(row.locator('.stance-badge')).toHaveClass(/negative/)
  await expect(row.locator('.stance-badge')).not.toHaveClass(/positive/)
})
