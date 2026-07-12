/**
 * 防线：界面文案国际化一致性。
 * 1) 方法全称：EN 下 Black-Litterman 不得被截成 "Assembly / fusion / views /
 *    Bayesian"（丢 Model）；可见方法名只能是五个英文全称。
 * 2) 组合驾驶舱「未来事件带」事件名必须走 t()，EN 下不残留中文短标签。
 * 3) 基点单位随语言取值（基点 / bp），不写死。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from '@playwright/test'

const src = (rel: string) =>
  readFileSync(fileURLToPath(new URL(`../src/${rel}`, import.meta.url)), 'utf8')

async function startInEnglish(page: Page) {
  await page.addInitScript(() => localStorage.setItem('ai_committee_lang_v1', 'en'))
}

test('EN 词典里 Black-Litterman 始终带 Model 全称', () => {
  for (const f of ['i18n/dict-core.ts', 'i18n/dict-a.ts', 'i18n/dict-b.ts']) {
    const dropped = src(f).match(/Black-Litterman(?! Model)/g)
    expect(dropped, `${f} 存在丢失 Model 的 Black-Litterman 串：${dropped}`).toBeNull()
  }
})

test('决策溯源 EN 下显示 Black-Litterman Model 全称而非缩写装配', async ({ page }) => {
  await startInEnglish(page)
  await page.goto('/trace')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.locator('.summary')).toBeVisible({ timeout: 45_000 })
  const body = await page.locator('body').innerText()
  expect(body).toContain('Black-Litterman Model')
  expect(body).not.toContain('Black-Litterman Assembly')
  await page.evaluate(() => localStorage.clear())
})

test('组合驾驶舱未来事件名随语言翻译（H3）', async ({ page }) => {
  await startInEnglish(page)
  await page.goto('/cockpit')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  // 事件名走 t()：EN 下应出现英文短标签而非中文原串
  await expect(page.getByText('China CPI/PPI Release').first()).toBeVisible({ timeout: 45_000 })
  expect(await page.locator('body').innerText()).not.toContain('中国 CPI/PPI 发布')
  // 源码守卫：事件名必须走 t()，防止回退成裸 {ev.name}
  expect(src('pages/CockpitPage.tsx')).toContain('t(ev.name)')
  await page.evaluate(() => localStorage.clear())
})

test('基点单位随语言取值，不写死 bp（M5）', () => {
  const cockpit = src('pages/CockpitPage.tsx')
  const spread = src('pages/SpreadDeskPage.tsx')
  // 组合驾驶舱月均 α 复用 meta.fmtBp（内部 tf 基点/bp）
  expect(cockpit).toContain('fmtBp(data.avg_alpha_vs_equal)')
  // 利差台两处基点单位走 tf('基点', 'bp')
  expect(spread).toContain("tf('基点', 'bp')")
})
