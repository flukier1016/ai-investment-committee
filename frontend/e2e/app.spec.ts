import { expect, test } from '@playwright/test'

const PAGES = [
  { path: '/overview', title: '总览' },
  { path: '/config', title: '配置' },
  { path: '/trace', title: '决策溯源' },
  { path: '/cockpit', title: '组合驾驶舱' },
  { path: '/scenarios', title: '情景回放' },
  { path: '/backtest', title: '回测分析' },
  { path: '/daily', title: '日更驾驶舱' },
  { path: '/weekly', title: '周度纪要' },
  { path: '/spread-desk', title: '利差台与风控' },
]

test('根路径按 V3 以三层溯源看板为主页面', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/trace$/)
  await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
})

test.describe('九模块加载', () => {
  for (const { path, title } of PAGES) {
    test(`页面 ${title} 正常加载`, async ({ page }) => {
      await page.goto(path)
      await expect(page.locator('.page-head h2').first()).toContainText(title, { timeout: 30_000 })
      await expect(page.locator('.loading-block')).toHaveCount(0, { timeout: 45_000 })
      await expect(page.locator('.error-block')).toHaveCount(0)
    })
  }
})

test.describe('决策溯源旗舰页', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/trace')
    await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
  })

  test('三层同屏 + 顶部最终结果在前', async ({ page }) => {
    await expect(page.locator('.final-result h2')).toContainText('合成目标权重')
    await expect(page.locator('#signals h2')).toContainText('四方法信号')
    await expect(page.locator('#bl h2')).toContainText('Black-Litterman Model')
    await expect(page.locator('#weights h2')).toContainText('最终权重与归因')
    // 最终结果必须在权重生成路径之前
    const summaryBox = await page.locator('.final-result').boundingBox()
    const pathBox = await page.locator('.path-panel').boundingBox()
    expect(summaryBox!.y).toBeLessThanOrEqual(pathBox!.y + 1)
  })

  test('闭合校验全部通过', async ({ page }) => {
    const statusCards = page.locator('.status-card .status-line')
    await expect(statusCards.nth(0)).toContainText('已通过')
    await expect(statusCards.nth(1)).toContainText('已通过')
  })

  test('可见区域不出现方法简称', async ({ page }) => {
    const text = await page.locator('.trace-page').innerText()
    for (const banned of ['CTA', 'TSMOM']) {
      expect(text).not.toContain(banned)
    }
    // ERP/BL 不得作为独立词出现（bl_inputs 等机器字段不在可见文本）
    expect(/\bERP\b/.test(text)).toBeFalsy()
    expect(text).toContain('Risk Parity')
    expect(text).toContain('Time Series Momentum')
    expect(text).toContain('Merrill Lynch Investment Clock')
    expect(text).toContain('Equity Risk Premium')
    expect(text).toContain('Black-Litterman Model')
  })

  test('点击信号卡打开血缘抽屉', async ({ page }) => {
    await page.locator('.signal-card').first().click()
    await expect(page.locator('.drawer')).toHaveClass(/open/)
    await expect(page.locator('.drawer-body')).toContainText('信号ID')
    await expect(page.locator('.drawer-body')).toContainText('代码版本')
    await page.keyboard.press('Escape')
    await expect(page.locator('.drawer')).not.toHaveClass(/open/)
  })

  test('点击观点卡高亮源信号并展示 P/Q/Ω', async ({ page }) => {
    await page.locator('.view-card').first().click()
    await expect(page.locator('.drawer')).toHaveClass(/open/)
    await expect(page.locator('.drawer-body')).toContainText('观点ID')
    await expect(page.locator('.drawer-body')).toContainText('不确定性')
    await expect(page.locator('.signal-card.selected')).toHaveCount(1)
  })

  test('归因段点击回链观点与信号', async ({ page }) => {
    // 默认只展开影响最大的桶（V3 §5.5），点击展开桶内的观点贡献段
    const part = page.locator('details.attrib-drill[open] button.part').first()
    await part.scrollIntoViewIfNeeded()
    await part.click()
    await expect(page.locator('.drawer')).toHaveClass(/open/)
    await expect(page.locator('.drawer-body')).toContainText('来源信号')
  })

  test('技术工作台：P 矩阵 27 列 + 行跳计算', async ({ page }) => {
    await page.getByText('打开技术工作台').click()
    await expect(page.locator('.modal')).toHaveClass(/open/)
    await expect(page.locator('.wide-matrix thead .matrix-asset-head')).toHaveCount(27)
    await page.locator('.matrix-trace-link').first().click()
    await expect(page.locator('.trace-view-card.focused')).toHaveCount(1)
    await expect(page.locator('.trace-view-card.focused')).toContainText('输入与指纹')
  })

  test('底部附录：27 明细资产展开', async ({ page }) => {
    await page.getByText('显示全部明细').click()
    await expect(page.locator('.detail-table tbody tr')).toHaveCount(27)
  })
})

test.describe('情景与配置联动', () => {
  test('切换情景改变决策批次', async ({ page }) => {
    await page.goto('/trace')
    await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
    const badge1 = await page.locator('.meta .badge').nth(1).innerText()
    await page.locator('.scenario-picker select').selectOption('stagflation_2022')
    await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
    await expect(page.locator('.meta .badge').nth(1)).not.toHaveText(badge1)
    await expect(page.locator('.meta .badge').first()).toContainText('2022年')
    // 复位
    await page.locator('.scenario-picker select').selectOption('recovery_2026')
  })

  test('配置页重新计算触发完整链路', async ({ page }) => {
    await page.goto('/config')
    await expect(page.locator('.loading-block')).toHaveCount(0, { timeout: 30_000 })
    await page.getByRole('button', { name: /重新计算/ }).click()
    await expect(page.getByText(/决策批次/).first()).toBeVisible({ timeout: 60_000 })
    // 清理本地配置，避免影响其他用例
    await page.evaluate(() => localStorage.clear())
  })
})

test('移动端视口无横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/trace')
  await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(2)
})

test('主题与语言切换', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/trace')
  await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  // 夜间模式
  await page.locator('.pref-btn').first().click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  // 英文模式
  await page.locator('.pref-btn').nth(1).click()
  await expect(page.locator('.page-head h2').first()).toContainText('Decision Trace')
  await expect(page.locator('.app-nav a').first()).toContainText('Overview')
  await expect(page.locator('.final-result h2')).toContainText('Composite Target Weights')
  // 复位（localStorage 持久化，避免影响其他用例）
  await page.evaluate(() => localStorage.clear())
})

test('委员会正反检验与结果账本', async ({ page }) => {
  await page.goto('/trace')
  await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
  const committee = page.locator('section.panel', { hasText: '委员会正反检验' })
  await expect(committee).toBeVisible()
  const first = committee.locator('details.attrib-drill').first()
  await first.locator('summary').click()
  await expect(first).toContainText('回应')
  await page.goto('/cockpit')
  await expect(page.locator('.app-card', { hasText: '决策命中率' })).toBeVisible({ timeout: 90_000 })
  await expect(page.locator('.app-card', { hasText: '决策命中率' })).toContainText('%', { timeout: 90_000 })
})
