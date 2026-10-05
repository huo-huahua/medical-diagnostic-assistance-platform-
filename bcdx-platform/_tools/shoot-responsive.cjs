// Responsive captures: the `md` (tablet) and phone layouts.
//
// The other screenshot script shoots at 1680x1050 only, where the sidebar is
// the full-width version and the compact header is `lg:hidden` — so neither the
// icon rail nor the header-mounted disease switcher is ever visible in those
// shots. These two capture the layouts that changed.
//
// Run with NODE_PATH pointing at the workspace node_modules so `puppeteer-core`
// resolves:
//   NODE_PATH="C:/Users/ASUS/.workbuddy/binaries/node/workspace/node_modules" \
//     node _tools/shoot-responsive.cjs docs/screenshots
const puppeteer = require('puppeteer-core')
const path = require('path')

const CHROME = 'C:/Users/ASUS/.agent-browser/browsers/chrome-154.0.8037.57/chrome.exe'
const OUT = process.argv[2] || '.'
const API = 'http://127.0.0.1:8000'
const APP = 'http://127.0.0.1:5173'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

;(async () => {
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
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  })

  const shoot = async (name, width, height, route, readyText) => {
    const page = await browser.newPage()
    await page.setViewport({ width, height, deviceScaleFactor: 1 })
    page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 160)))
    await page.evaluateOnNewDocument((t) => {
      localStorage.setItem('bcdx.token', t)
    }, token)
    await page.goto(`${APP}${route}`, { waitUntil: 'networkidle2' })
    await page.waitForFunction(
      (t) => document.body.innerText.includes(t),
      { timeout: 25000 },
      readyText,
    )
    await sleep(1400)

    // Assert the thing this shot exists to show, so a silently-broken layout
    // fails loudly instead of producing a plausible-looking screenshot.
    const probe = await page.evaluate(() => {
      const header = document.querySelector('header')
      const aside = document.querySelector('aside')
      const visible = (el) =>
        !!el && getComputedStyle(el).display !== 'none' && el.offsetWidth > 0
      const pressed = document.querySelectorAll('[aria-pressed]').length
      return {
        headerVisible: visible(header),
        headerButtons: header ? header.querySelectorAll('[aria-pressed]').length : 0,
        asideWidth: aside ? aside.offsetWidth : 0,
        pressed,
      }
    })
    console.log(`  ${name}: ${JSON.stringify(probe)}`)
    await page.screenshot({ path: path.join(OUT, name) })
    console.log(`captured ${name}`)
    await page.close()
    return probe
  }

  // 820px sits inside the `md` band: the sidebar collapses to a 64px icon rail
  // AND the compact header is still shown, so the disease switcher is reachable
  // there — which is the whole point of the `md` work.
  const tablet = await shoot(
    '17-tablet-rail.png', 820, 1180, '/dashboard', 'BC-Dx Platform',
  )
  if (!tablet.headerButtons) {
    throw new Error(
      'tablet header has no [aria-pressed] switcher — the disease module would ' +
        'be unreachable at this width',
    )
  }

  await shoot('18-phone-header.png', 390, 844, '/assistant', 'BC-Dx Platform')

  await browser.close()
  console.log('done')
})().catch((e) => {
  console.error('FAILED:', e.message)
  process.exit(1)
})
