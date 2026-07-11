// 交付截图：桌面完整长页 + 移动端（决策溯源旗舰页 + 总览）
// 用法：先启动前后端，再 node scripts/capture_screenshots.mjs [baseURL]
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'

const base = process.argv[2] ?? 'http://localhost:5173'
const outDir = new URL('../../docs/previews/', import.meta.url).pathname
mkdirSync(outDir, { recursive: true })

const browser = await chromium.launch()

async function shoot(name, path, viewport, fullPage = true) {
  const page = await browser.newPage({ viewport })
  await page.goto(`${base}${path}`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.page-head h2', { timeout: 60000 })
  await page.waitForFunction(() => !document.querySelector('.loading-block'), { timeout: 60000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${outDir}${name}.png`, fullPage })
  console.log(`saved ${name}.png`)
  await page.close()
}

await shoot('trace_desktop_full', '/trace', { width: 1680, height: 1000 })
await shoot('trace_mobile', '/trace', { width: 390, height: 844 })
await shoot('overview_desktop', '/', { width: 1680, height: 1000 })
await shoot('backtest_desktop', '/backtest', { width: 1680, height: 1000 })
await browser.close()
