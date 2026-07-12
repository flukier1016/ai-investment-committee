/**
 * 防线：可访问性与暗色可见性。
 * M4 利差台策略行必须键盘可达且可回车/空格展开，不只鼠标可点。
 * M3 技术工作台 aria-label 走 tf()，读屏在 EN 下不念中文。
 * M1 信号卡与高亮行背景走主题令牌（--surface-*），不写死暗色 rgba（暗色下不可见）。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const src = (rel: string) =>
  readFileSync(fileURLToPath(new URL(`../src/${rel}`, import.meta.url)), 'utf8')

test('利差台策略行键盘可达并可回车展开（M4）', async ({ page }) => {
  await page.goto('/spread-desk')
  const firstRow = page.locator('tbody tr[tabindex="0"]').first()
  await expect(firstRow).toBeVisible({ timeout: 45_000 })
  await expect(firstRow).toHaveAttribute('aria-expanded', 'false')
  await firstRow.focus()
  await page.keyboard.press('Enter')
  await expect(firstRow).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('近期交易').first()).toBeVisible()
})

test('技术工作台 aria-label 走 tf 而非硬编码中文（M3）', () => {
  const trace = src('pages/TracePage.tsx')
  expect(trace).not.toContain('aria-label="Black-Litterman Model 技术细节"')
  expect(trace).not.toContain('aria-label="技术细节视图"')
  expect(trace).toContain("tf('技术细节视图'")
})

test('信号卡与高亮行背景走主题令牌而非写死 rgba（M1）', () => {
  expect(src('pages/ScenariosPage.tsx')).not.toContain('rgba(29,41,37')
  expect(src('pages/BacktestPage.tsx')).not.toContain('rgba(64, 93, 136')
})
