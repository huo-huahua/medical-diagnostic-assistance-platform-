// Screenshot the two new pages. Run with NODE_PATH pointing at the workspace
// node_modules so `puppeteer-core` resolves.
const puppeteer = require('puppeteer-core')
const fs = require('fs')
const path = require('path')

const CHROME = 'C:/Users/ASUS/.agent-browser/browsers/chrome-154.0.8037.57/chrome.exe'
const OUT = process.argv[2] || '.'
const API = 'http://127.0.0.1:8000'
const APP = 'http://127.0.0.1:5173'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** Click the first <button> whose trimmed text contains `needle`. */
async function clickByText(page, needle, exact = false) {
  const ok = await page.evaluate(
    (needle, exact) => {
      const btns = [...document.querySelectorAll('button')]
      const hit = btns.find((b) => {
        const t = (b.textContent || '').trim()
        return exact ? t === needle : t.includes(needle)
      })
      if (!hit) return false
      hit.scrollIntoView({ block: 'center' })
      hit.click()
      return true
    },
    needle,
    exact,
  )
  if (!ok) throw new Error(`button not found: ${needle}`)
}

;(async () => {
  // --- get a token over REST ---
  const res = await fetch(`${API}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'demo@bcdx.dev', password: 'demo12345' }),
  })
  if (!res.ok) throw new Error(`login failed: ${res.status} ${await res.text()}`)
  const token = (await res.json()).data.access_token
  console.log('token acquired')

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1680,1050'],
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1680, height: 1050, deviceScaleFactor: 1 })

  page.on('console', (m) => {
    if (m.type() === 'error') console.log('  [console.error]', m.text().slice(0, 200))
  })
  page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 200)))

  // Seed the session before the SPA boots. The key is `bcdx.token`.
  await page.evaluateOnNewDocument((t) => {
    localStorage.setItem('bcdx.token', t)
  }, token)

  /* ----------------------------- batch page ----------------------------- */
  await page.goto(`${APP}/batch`, { waitUntil: 'networkidle2' })
  await page.waitForFunction(() => document.body.innerText.includes('批量评估'), { timeout: 20000 })
  await sleep(1200)

  await clickByText(page, '载入 12 份真实样本')
  await page.waitForFunction(() => document.body.innerText.includes('已解析 12 行'), { timeout: 20000 })
  await sleep(800)
  await page.screenshot({ path: path.join(OUT, '09-batch-input.png') })
  console.log('captured 09-batch-input.png')

  await clickByText(page, '开始批量评估')
  await page.waitForFunction(() => document.body.innerText.includes('样本总数'), { timeout: 40000 })
  await sleep(1500)

  // Scroll the metric strip into view for the results shot.
  await page.evaluate(() => {
    const h = [...document.querySelectorAll('h2')].find((e) => e.textContent.includes('概率分布'))
    if (h) h.scrollIntoView({ block: 'start' })
  })
  await sleep(700)
  await page.screenshot({ path: path.join(OUT, '10-batch-results.png') })
  console.log('captured 10-batch-results.png')

  await page.evaluate(() => {
    const h = [...document.querySelectorAll('h2')].find((e) => e.textContent.includes('逐行结果'))
    if (h) h.scrollIntoView({ block: 'start' })
  })
  await sleep(700)
  await page.screenshot({ path: path.join(OUT, '11-batch-table.png') })
  console.log('captured 11-batch-table.png')

  /* --------------------------- qa compare page --------------------------- */
  await page.goto(`${APP}/qa-compare`, { waitUntil: 'networkidle2' })
  await page.waitForFunction(() => document.body.innerText.includes('问答路径对比'), { timeout: 20000 })
  await sleep(1200)
  await page.screenshot({ path: path.join(OUT, '12-compare-idle.png') })
  console.log('captured 12-compare-idle.png')

  await clickByText(page, 'BI-RADS 分级是什么意思？')
  await page.waitForFunction(() => document.body.innerText.includes('指标对照'), { timeout: 40000 })
  await sleep(1500)
  await page.evaluate(() => {
    const h = [...document.querySelectorAll('h2')].find((e) => e.textContent.includes('指标对照'))
    if (h) h.scrollIntoView({ block: 'start' })
  })
  await sleep(700)
  await page.screenshot({ path: path.join(OUT, '13-compare-metrics.png') })
  console.log('captured 13-compare-metrics.png')

  await page.evaluate(() => {
    const h = [...document.querySelectorAll('h2')].find((e) => e.textContent.includes('怎么读这张表'))
    if (h) h.scrollIntoView({ block: 'start' })
  })
  await sleep(700)
  await page.screenshot({ path: path.join(OUT, '14-compare-reading.png') })
  console.log('captured 14-compare-reading.png')

  /* ------------------------- llm connection panel ------------------------- */
  // Open the provider catalogue and run the probe, so the shot shows the
  // panel doing its job rather than an idle card.
  await page.evaluate(() => {
    const d = [...document.querySelectorAll('details')].find((e) =>
      (e.querySelector('summary')?.textContent || '').includes('服务商'),
    )
    if (d) d.open = true
  })
  await clickByText(page, '测试连接')
  await page.waitForFunction(
    () => /连接正常|调用失败|未配置密钥|已关闭/.test(document.body.innerText),
    { timeout: 30000 },
  )
  await sleep(1000)

  const panelHandle = await page.evaluateHandle(() => {
    const h = [...document.querySelectorAll('h2')].find((e) =>
      e.textContent.includes('外部模型连接'),
    )
    return h ? h.closest('section') : null
  })
  const panelEl = panelHandle.asElement()
  if (!panelEl) throw new Error('LLM panel not found')
  await panelEl.screenshot({ path: path.join(OUT, '15-llm-panel.png') })
  console.log('captured 15-llm-panel.png')

  /* --------------------------- multi-model run --------------------------- */
  // React owns the input value, so write through the native setter and fire
  // an input event, otherwise the component never sees the change.
  const MODELS = 'model-a, model-b'
  await page.evaluate((val) => {
    const input = [...document.querySelectorAll('input[type="text"]')].find((i) =>
      (i.placeholder || '').includes('gpt-4o-mini'),
    )
    if (!input) return
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value',
    ).set
    setter.call(input, val)
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.scrollIntoView({ block: 'center' })
  }, MODELS)
  await sleep(500)

  await clickByText(page, 'BI-RADS 分级是什么意思？')
  await page.waitForFunction(
    () => document.body.innerText.includes('model-b'),
    { timeout: 60000 },
  )
  await sleep(1200)
  await page.evaluate(() => {
    const h = [...document.querySelectorAll('h2')].find((e) =>
      e.textContent.includes('指标对照'),
    )
    if (h) h.scrollIntoView({ block: 'start' })
  })
  await sleep(800)
  await page.screenshot({ path: path.join(OUT, '16-compare-multi-model.png') })
  console.log('captured 16-compare-multi-model.png')

  await browser.close()
  console.log('done')
})().catch((e) => {
  console.error('FAILED:', e.message)
  process.exit(1)
})
