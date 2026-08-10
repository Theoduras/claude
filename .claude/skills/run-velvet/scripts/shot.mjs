// Log into Velvet and screenshot a page.
// Usage: node shot.mjs [path] [output] [username] [password]
import { createRequire } from 'node:module';

// Node resolves bare imports relative to this file, but playwright is installed
// wherever you ran `npm i` (usually the scratchpad). Resolve from cwd instead.
// require, not import(): playwright is CommonJS, so its named exports only come
// through cleanly this way.
const require = createRequire(import.meta.url);
const { chromium } = require(
  require.resolve('playwright', { paths: [process.cwd(), import.meta.dirname] }),
);

const [path = '/browse', out = 'velvet.png', user = 'mia_b', pass = 'demo12345'] =
  process.argv.slice(2);
const base = process.env.VELVET_URL || 'http://127.0.0.1:5000';

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });

page.on('pageerror', (e) => console.log('pageerror:', e.message));

await page.goto(`${base}/login`);
await page.fill('input[name=username]', user);
await page.fill('input[name=password]', pass);
await page.click('button[type=submit]');
await page.waitForLoadState('networkidle');

if (page.url().includes('/login')) {
  console.log('WARNING: still on /login — credentials rejected or seed data missing');
}

await page.goto(base + path);
await page.waitForLoadState('networkidle');
await page.screenshot({ path: out });
console.log('url:', page.url(), '->', out);

await browser.close();
