/**
 * 防线：风控三人格卡必须逐项展示后端派生事实，不能在浏览器重算利用率/上限/半 L1；
 * 三卡固定顺序、完整 i18n、移动端无溢出，并只使用中性色而不占五方法或红绿语义。
 */
import { expect, test } from '@playwright/test'

interface RiskPerspective {
  role: 'aggressive' | 'conservative' | 'neutral'
  metric: string
  value: number
  metrics: Record<string, number | string>
}

interface RiskBundle {
  committee_review: { risk_perspectives: RiskPerspective[] }
}

test('三人格固定展示后端值并支持中英移动端', async ({ page }) => {
  await page.route('**/api/decisions/run', async (route) => {
    const response = await route.fetch()
    const bundle = await response.json() as RiskBundle
    const aggressive = bundle.committee_review.risk_perspectives.find((item) => item.role === 'aggressive')!
    const conservative = bundle.committee_review.risk_perspectives.find((item) => item.role === 'conservative')!
    const neutral = bundle.committee_review.risk_perspectives.find((item) => item.role === 'neutral')!

    // 故意与 checks/config 及明细权重制造矛盾：页面必须服从后端三视角字段。
    aggressive.value = 0.9876
    aggressive.metrics.utilization = 0.9876
    conservative.value = 0.0456
    conservative.metrics.headroom = 0.0456
    conservative.metrics.current = 0.1234
    conservative.metrics.limit = 0.2345
    neutral.value = 0.1234
    neutral.metrics.explainable_share = 0.1234
    neutral.metrics.asset_turnover_proxy = 0.2222
    neutral.metrics.bucket_shift = 0.1111
    bundle.committee_review.risk_perspectives.reverse()
    await route.fulfill({ response, json: bundle })
  })

  await page.goto('/trace')
  await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
  const section = page.getByTestId('risk-perspectives')
  const cards = section.locator('.risk-perspective-card')
  await expect(cards).toHaveCount(3)
  expect(await cards.evaluateAll((items) => items.map((item) => item.getAttribute('data-role')))).toEqual([
    'aggressive', 'conservative', 'neutral',
  ])
  await expect(cards.nth(0).locator('.risk-primary strong')).toHaveText('98.8%')
  await expect(cards.nth(1).locator('.risk-primary strong')).toHaveText('+4.56个百分点')
  await expect(cards.nth(1)).toContainText('12.34%')
  await expect(cards.nth(1)).toContainText('23.45%')
  await expect(cards.nth(2).locator('.risk-primary strong')).toHaveText('12.3%')
  await expect(cards.nth(2)).toContainText('22.22%')
  await expect(cards.nth(2)).toContainText('11.11%')
  await expect(cards.nth(2)).toContainText('换手代理，非实际成交')

  await page.locator('.pref-btn').nth(1).click()
  await expect(section.locator('h3')).toHaveText('Three Risk Perspectives')
  await expect(cards.nth(0)).toContainText('Aggressive View')
  await expect(cards.nth(1)).toContainText('Conservative View')
  await expect(cards.nth(2)).toContainText('Neutral View')
  await expect(cards.nth(0)).toContainText('Vol Budget Utilization')
  await expect(cards.nth(1)).toContainText('Headroom to Limits')
  await expect(cards.nth(2)).toContainText('Turnover Proportionality')
  await expect(cards.nth(0)).toContainText('Capacity Remaining')
  await expect(cards.nth(1)).toContainText('Headroom Available')
  await expect(cards.nth(2)).toContainText('Partly Explained by Buckets')
  await expect(cards.nth(0)).toContainText('Ex-ante vol')
  await expect(cards.nth(1)).toContainText('Nearest Effective Limit')
  await expect(cards.nth(2)).toContainText('One-Way Asset Turnover Proxy')
  await expect(cards.nth(2)).toContainText('Turnover proxy, not realized trading')

  await page.setViewportSize({ width: 900, height: 900 })
  const cardOverflow = await cards.evaluateAll((items) =>
    Math.max(...items.map((item) => item.scrollWidth - item.clientWidth)))
  expect(cardOverflow).toBeLessThanOrEqual(1)
  await page.setViewportSize({ width: 390, height: 844 })
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(2)
  await page.evaluate(() => localStorage.clear())
})

test('三人格亮暗主题只使用共同中性色且不套涨跌类', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/trace')
  await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })

  const inspectColors = () => page.locator('.risk-perspective-card').evaluateAll((cards) => {
    const resolveColor = (variable: string) => {
      const probe = document.createElement('span')
      probe.style.color = `var(${variable})`
      document.body.appendChild(probe)
      const color = getComputedStyle(probe).color
      probe.remove()
      return color
    }
    const forbiddenColors = [
      '--method-risk-parity', '--method-cta', '--method-clock', '--method-erp', '--bl',
      '--red', '--green',
    ].map(resolveColor)
    const neutral = resolveColor('--risk-perspective-accent')
    return cards.map((card) => {
      const accents = [
        getComputedStyle(card).borderTopColor,
        getComputedStyle(card.querySelector('.risk-persona')!).color,
        getComputedStyle(card.querySelector('.risk-assessment')!).color,
        getComputedStyle(card.querySelector('.risk-primary strong')!).color,
      ]
      const note = card.querySelector('.risk-perspective-note')
      if (note) accents.push(getComputedStyle(note).color)
      return {
        accents,
        neutral,
        forbiddenColors,
        hasDirectionClass: card.querySelector('.pos, .neg, .positive, .negative') !== null,
      }
    })
  })

  for (const result of await inspectColors()) {
    expect(result.accents.every((color) => color === result.neutral)).toBeTruthy()
    expect(result.accents.some((color) => result.forbiddenColors.includes(color))).toBeFalsy()
    expect(result.hasDirectionClass).toBeFalsy()
  }

  await page.locator('.pref-btn').first().click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  for (const result of await inspectColors()) {
    expect(result.accents.every((color) => color === result.neutral)).toBeTruthy()
    expect(result.accents.some((color) => result.forbiddenColors.includes(color))).toBeFalsy()
    expect(result.hasDirectionClass).toBeFalsy()
  }
})
