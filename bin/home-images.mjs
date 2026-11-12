#!/usr/bin/env node
// home-images.mjs SITE QUERY OUT_DIR
//
// The homepage's featured cards as pictures (hikeratlas/website#116): two
// MapLibre maps and an elevation profile from the DEM were heavy for the
// page's first look. For each showcase park (?showcase=N, as many as the
// page's park switcher lists), the page drawn live in its ?shots mode, each
// card's art (data-shot="park" and "hike", named by data-shot-name, the
// park's slug) pictured once it's drawn (data-ready) at 2x, as
// OUT_DIR/<slug>-park.jpg and -hike.jpg. QUERY is added to each URL (a
// build's "build=..."). Exits 1 if any park's pictures are missing, so the
// build doesn't point the site at them.
import { mkdirSync } from 'node:fs';
import { chromium } from 'playwright';

const [site, query, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const url = (i) => `${site}/?showcase=${i}&shots${query ? `&${query}` : ''}`;
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 }, deviceScaleFactor: 2 });

const first = await ctx.newPage();
await first.goto(url(0), { waitUntil: 'domcontentloaded' });
const n = await first.locator('nav[aria-label="Showcase parks"] div a').count();
await first.close();
if (!n) { console.error('No showcase parks on the page'); process.exit(1); }

let failed = 0;
async function shoot(i) {
  const p = await ctx.newPage();
  try {
    await p.goto(url(i), { waitUntil: 'domcontentloaded' });
    const park = p.locator('[data-shot="park"]');
    const hike = p.locator('[data-shot="hike"]');
    await park.locator('[data-ready]').waitFor({ timeout: 90_000 });
    // The hike's map and its elevation profile.
    await p.waitForFunction(() => document.querySelectorAll('[data-shot="hike"] [data-ready]').length >= 2, null, { timeout: 90_000 });
    // Web fonts and the last tiles' fade-in.
    await p.evaluate(() => document.fonts.ready);
    await p.waitForTimeout(800);
    const slug = await park.getAttribute('data-shot-name');
    await park.screenshot({ path: `${out}/${slug}-park.jpg`, type: 'jpeg', quality: 82 });
    await hike.screenshot({ path: `${out}/${slug}-hike.jpg`, type: 'jpeg', quality: 82 });
    console.log(`${i + 1}/${n} ${slug}`);
  } catch (e) {
    failed++;
    console.error(`${i + 1}/${n}: ${e.message.split('\n')[0]}`);
  } finally {
    await p.close();
  }
}

// A few at once.
const queue = [...Array(n).keys()];
await Promise.all([...Array(4)].map(async () => { while (queue.length) await shoot(queue.shift()); }));
await browser.close();
console.log(`${n - failed} of ${n} showcase parks pictured`);
process.exit(failed ? 1 : 0);
