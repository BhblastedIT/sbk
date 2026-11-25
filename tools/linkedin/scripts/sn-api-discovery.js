#!/usr/bin/env node



























'use strict';

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const safety = require('./li-safety.js');

const OUTPUT_DIR = path.join(__dirname, '..', '..', 'sbk', 'raw', 'linkedin');
const SESSION_FILE = path.join(OUTPUT_DIR, 'linkedin-session.json');


const DISCOVERY_SESSION_CAP = 10;




function parseArgs(argv) {
  const args = { run: false, yes: false };
  for (const a of argv.slice(2)) {
    if (a === '--run') args.run = true;
    else if (a === '--yes' || a === '-y') args.yes = true;
    else if (a === '--help' || a === '-h') args.help = true;
  }
  return args;
}

function printUsage() {
  process.stdout.write(
    'SBK — Sales Navigator API Discovery (live LinkedIn tool, gated)\n\n' +
      'Usage:\n' +
      '  node sn-api-discovery.js            # dry-run: prints plan, does nothing\n' +
      '  node sn-api-discovery.js --run      # actually drives SN (asks confirmation)\n' +
      '  node sn-api-discovery.js --run --yes# skip the interactive confirmation\n\n' +
      'Safety:\n' +
      `  - Refuses to start if kill-switch lock exists (${safety.KILLSWITCH_LOCK}).\n` +
      `  - Session cap: ${DISCOVERY_SESSION_CAP} significant actions. Daily cap: ${safety.DEFAULT_DAILY_CAP} (shared).\n` +
      '  - Delays between actions: jittered 45s..120s (NEVER the old 8000/5000/2000ms).\n' +
      '  - Any 429/999/403/authwall/challenge aborts and trips the global kill-switch.\n'
  );
}

function confirm(question) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(question, (ans) => {
      rl.close();
      resolve(/^y(es)?$/i.test((ans || '').trim()));
    });
  });
}


(async () => {
  const args = parseArgs(process.argv);

  if (args.help) {
    printUsage();
    process.exit(0);
  }





  if (process.env.LI_ALLOW_SN_BROWSER !== '1') {
    process.stderr.write(
      '\n⛔ Sales Navigator browser discovery DISABLED for safety.\n' +
      '   Untracked request bursts → risk of account restriction.\n' +
      '   To force it at your own risk: LI_ALLOW_SN_BROWSER=1 node sn-api-discovery.js --run\n\n'
    );
    process.exit(0);
  }


  if (!args.run) {
    printUsage();
    process.stdout.write(
      '\n[dry-run] --run not passed. Nothing was sent to LinkedIn. Exiting.\n'
    );
    process.exit(0);
  }


  safety.checkKillswitch();


  if (!args.yes) {
    const ok = await confirm(
      'This drives a LIVE Sales Navigator session (can trigger anti-automation).\n' +
        `Session cap ${DISCOVERY_SESSION_CAP}, shared daily cap ${safety.DEFAULT_DAILY_CAP}, 45-120s between actions.\n` +
        'Proceed? [y/N] '
    );
    if (!ok) {
      process.stdout.write('Aborted by user. Nothing sent to LinkedIn.\n');
      process.exit(0);
    }
  }


  const guard = new safety.LinkedInSafetyGuard({ sessionCap: DISCOVERY_SESSION_CAP });




  async function safeAction(label, fn) {
    guard.assertUnderCaps(); // throws if next action breaches session/daily cap
    const waited = await guard.randomDelay();
    console.log(`  [safety] waited ${(waited / 1000).toFixed(1)}s before: ${label}`);
    const result = await fn();
    guard.recordCall(); // count one effective LinkedIn-touching action
    return result;
  }

  console.log('=== Sales Navigator API Discovery (gated, conservative) ===\n');

  const browser = await chromium.launch({
    headless: false,
    args: ['--window-size=1400,900'],
  });

  const context = await browser.newContext({
    storageState: SESSION_FILE,
    viewport: { width: 1400, height: 900 },
  });

  const page = await context.newPage();

  const apiCalls = [];
  const sampleResponses = {};




  page.on('response', async (response) => {
    const url = response.url();
    if (!url.includes('linkedin.com')) return;



    const status = response.status();
    if (status === 429 || status === 999 || status === 403) {

      guard.classifyResponse({ status, url }, '');
      return;
    }

    if (status !== 200) return;

    if (
      url.includes('.js') ||
      url.includes('.css') ||
      url.includes('.png') ||
      url.includes('.jpg') ||
      url.includes('.svg') ||
      url.includes('.woff')
    )
      return;
    if (
      url.includes('tracking') ||
      url.includes('analytics') ||
      url.includes('impression') ||
      url.includes('lnkd.demdex') ||
      url.includes('li/track')
    )
      return;

    const contentType = response.headers()['content-type'] || '';
    if (!contentType.includes('json')) return;

    const shortUrl = url.replace('https://www.linkedin.com', '');
    apiCalls.push(shortUrl);


    const pattern = shortUrl.split('?')[0];
    if (!sampleResponses[pattern]) {
      try {
        const text = await response.text();

        guard.classifyResponse({ status, url }, text);

        const json = JSON.parse(text);
        const keys = Object.keys(json);
        const included = json.included || [];
        const types = [...new Set(included.map((i) => i['$type'] || i._type || 'unknown'))];

        sampleResponses[pattern] = {
          url: shortUrl.substring(0, 200),
          topLevelKeys: keys,
          includedCount: included.length,
          includedTypes: types,
          elementsCount: (json.elements || json.data?.elements || []).length,
          hasData: !!json.data,
        };

        console.log(`  API: ${shortUrl.substring(0, 120)}`);
        console.log(
          `       Keys: ${keys.join(', ')} | Included: ${included.length} types: ${types.join(', ')}\n`
        );
      } catch (e) {

      }
    }
  });

  try {

    console.log('[1] Opening Sales Navigator inbox...\n');
    await safeAction('navigate SN inbox', () =>
      page.goto('https://www.linkedin.com/sales/inbox/', {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      })
    );

    console.log(`\nCurrent URL: ${page.url()}`);
    console.log(`API calls so far: ${apiCalls.length}\n`);


    console.log('[2] Trying to click a conversation...\n');


    const pageInfo = await page.evaluate(() => {
      const all = document.querySelectorAll('*');
      const classes = new Set();
      const withScroll = [];
      for (const el of all) {
        if (el.className && typeof el.className === 'string') {
          for (const cls of el.className.split(' ')) {
            if (
              cls.includes('inbox') ||
              cls.includes('conversation') ||
              cls.includes('thread') ||
              cls.includes('message') ||
              cls.includes('list') ||
              cls.includes('chat')
            ) {
              classes.add(cls);
            }
          }
        }
        if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 100) {
          withScroll.push({
            tag: el.tagName,
            class: (el.className || '').toString().substring(0, 100),
            scrollH: el.scrollHeight,
            clientH: el.clientHeight,
          });
        }
      }


      const listItems = document.querySelectorAll('li');
      const links = document.querySelectorAll('a[href*="inbox"], a[href*="thread"]');

      return {
        relevantClasses: [...classes].slice(0, 50),
        scrollableElements: withScroll.slice(0, 10),
        totalListItems: listItems.length,
        inboxLinks: [...links].map((a) => a.href).slice(0, 10),
        bodyText: document.body.innerText.substring(0, 500),
      };
    });

    console.log('Page structure:');
    console.log(`  Relevant classes: ${pageInfo.relevantClasses.join(', ')}`);
    console.log(`  Scrollable elements: ${pageInfo.scrollableElements.length}`);
    for (const s of pageInfo.scrollableElements) {
      console.log(`    <${s.tag}> class="${s.class}" scroll=${s.scrollH} client=${s.clientH}`);
    }
    console.log(`  Total list items: ${pageInfo.totalListItems}`);
    console.log(`  Inbox links: ${pageInfo.inboxLinks.join('\n    ')}`);
    console.log(`  Body text (start): ${pageInfo.bodyText.substring(0, 300)}\n`);


    const clicked = await safeAction('click first conversation', () =>
      page.evaluate(() => {

        const items = document.querySelectorAll('li');
        for (const item of items) {
          const text = item.innerText || '';

          if (text.length < 10) continue;

          const link = item.querySelector('a') || item;
          if (link) {
            link.click();
            return `Clicked: ${text.substring(0, 80)}`;
          }
        }
        return 'No items clicked';
      })
    );
    console.log(`  ${clicked}\n`);

    console.log(`\nAPI calls after click: ${apiCalls.length}\n`);



    console.log('[3] Scrolling conversation list (capped, spaced)...\n');

    for (let i = 0; i < 5; i++) {

      try {
        guard.assertUnderCaps();
      } catch (e) {
        console.log(`  [safety] stopping scrolls early: ${e.message}`);
        break;
      }
      await safeAction(`scroll burst ${i + 1}`, () =>
        page.evaluate(() => {
          document.querySelectorAll('div, aside, section, ul, nav').forEach((el) => {
            if (el.scrollHeight > el.clientHeight + 100 && el.clientHeight > 100) {
              el.scrollTop = el.scrollHeight;
            }
          });
        })
      );
      console.log(`  Scroll ${i + 1}: ${apiCalls.length} API calls total`);
    }
  } catch (e) {

    console.log(`\n[safety] Run halted: ${e.message}`);
  }


  console.log('\n=== SUMMARY ===\n');
  console.log(`Total API calls intercepted: ${apiCalls.length}`);
  console.log(`Unique endpoint patterns: ${Object.keys(sampleResponses).length}\n`);

  console.log('All endpoint patterns:');
  for (const [pattern, info] of Object.entries(sampleResponses)) {
    console.log(`  ${pattern}`);
    console.log(`    Keys: ${info.topLevelKeys.join(', ')}`);
    console.log(`    Included: ${info.includedCount} | Elements: ${info.elementsCount}`);
    console.log(`    Types: ${info.includedTypes.join(', ')}\n`);
  }


  const discoveryFile = path.join(OUTPUT_DIR, '.sn-api-discovery.json');
  fs.writeFileSync(
    discoveryFile,
    JSON.stringify(
      {
        allUrls: apiCalls,
        patterns: sampleResponses,
        timestamp: new Date().toISOString(),
      },
      null,
      2
    )
  );
  console.log(`\nSaved discovery data → ${discoveryFile}`);

  await browser.close();
})();
