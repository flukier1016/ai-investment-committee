/**
 * 防线：五个含 ECharts 的页面（回测 / 组合驾驶舱 / 日更 / 情景 / 利差台）的图表
 * 颜色只能取自 meta.ts 的 SOLID 常量与随主题取值的 chartTheme()，不得回退到写死
 * 的 hex；尤其禁止旧的亮色网格线 #dde4db 在暗色主题下刺穿背景。
 * 附一条暗色渲染烟测，确保「网格/轴色随主题取值」的重构没有破坏图表渲染本身。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const CHART_PAGES = [
  'BacktestPage.tsx', 'CockpitPage.tsx', 'DailyPage.tsx', 'ScenariosPage.tsx', 'SpreadDeskPage.tsx',
]

// 迁移前散落在图表 option 里的写死颜色：亮色网格 + 各系列身份色的字面 hex。
// 迁移后这些字面量都应改为 SOLID.* / chartTheme(theme).*，任何一个重新出现即回归。
const FORBIDDEN_HEX = [
  '#dde4db', '#405d88', '#16806b', '#66706c', '#9f6500', '#4f5964',
  '#b84c48', '#0b7668', '#8a5b06', '#247a54',
]

test('图表页颜色只走 SOLID / chartTheme，无写死 hex 与亮色网格', () => {
  for (const pageFile of CHART_PAGES) {
    const src = readFileSync(fileURLToPath(new URL(`../src/pages/${pageFile}`, import.meta.url)), 'utf8')
    for (const hex of FORBIDDEN_HEX) {
      expect(src.includes(hex), `${pageFile} 不应再包含写死颜色 ${hex}`).toBeFalsy()
    }
    expect(src.includes('chartTheme'), `${pageFile} 应引入 chartTheme 以随主题取网格/轴色`).toBeTruthy()
  }
})

test('图表在暗色主题下正常渲染（网格随主题重构未破坏图表）', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('ai_committee_theme_v1', 'dark'))
  await page.goto('/backtest')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  // 回测页净值图应渲染出 ECharts canvas，且没有错误块
  await expect(page.locator('.app-card canvas').first()).toBeVisible({ timeout: 45_000 })
  await expect(page.locator('.error-block')).toHaveCount(0)
  await page.evaluate(() => localStorage.clear())
})
