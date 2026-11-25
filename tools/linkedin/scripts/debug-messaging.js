#!/usr/bin/env node





























'use strict';

const { chromium } = require('playwright');
const safety = require('./li-safety.js');


const CONFIRM =
  process.argv.includes('--confirm') || process.env.LI_DEBUG_CONFIRM === '1';

if (!CONFIRM) {
  process.stderr.write(
    '[debug-messaging] This is a one-off DEBUG tool that opens LinkedIn /messaging/ live.\n' +
      '  It is gated to avoid triggering LinkedIn account restrictions.\n' +
      '  Re-run with `--confirm` (or LI_DEBUG_CONFIRM=1) to actually open the page.\n' +
      '  Nothing was done. No LinkedIn calls made.\n'
  );
  process.exit(0);
}

(async () => {


  safety.checkKillswitch();



  const guard = new safety.LinkedInSafetyGuard({ sessionCap: 1 });
  guard.assertUnderCaps(); // refuse if the 40/day aggregate is already spent

  const browser = await chromium.launch({ headless: true, slowMo: 100 });
  const context = await browser.newContext({ storageState: './linkedin-session.json' });
  const page = await context.newPage();

  let responseCount = 0;
  let killswitchTripped = false;

  page.on('response', async response => {
    const url = response.url();
    if (url.indexOf('MessagingGraphQL') === -1 && url.indexOf('messengerConversation') === -1) return;

    responseCount++;
    let text = '';
    try {
      text = await response.text();
    } catch (e) {

    }




    try {
      safety.classifyResponse(
        { status: response.status(), url },
        text
      );
    } catch (e) {
      killswitchTripped = true;
    }

    try {
      const json = JSON.parse(text);

      const topIncluded = json.included || [];
      const dataIncluded = json.data ? (json.data.included || []) : [];

      console.log('---');
      console.log('URL:', url.replace('https://www.linkedin.com/voyager/api', '').substring(0, 120));
      console.log('Top keys:', Object.keys(json));
      console.log('top.included:', topIncluded.length, '| data.included:', dataIncluded.length);


      if (json.data) {
        console.log('data keys:', Object.keys(json.data));
        if (json.data.data) {
          console.log('data.data keys:', Object.keys(json.data.data));

          const dd = json.data.data;
          for (const [k, v] of Object.entries(dd)) {
            if (v && typeof v === 'object') {
              if (v['*elements']) console.log(`  ${k}.*elements:`, v['*elements'].length);
              if (v.elements) console.log(`  ${k}.elements:`, v.elements.length);
              if (v.included) console.log(`  ${k}.included:`, v.included.length);
            }
          }
        }

        const sample = JSON.stringify(json.data).substring(0, 500);
        console.log('data sample:', sample);
      }
    } catch (e) {
      console.log('Parse error:', e.message.substring(0, 100));
    }
  });


  guard.recordCall();
  await page.goto('https://www.linkedin.com/messaging/', { waitUntil: 'domcontentloaded' });

  await page.waitForTimeout(10000);

  console.log('\n=== Total messaging responses:', responseCount);
  if (killswitchTripped) {
    console.log('=== A response tripped the kill-switch; account may be restricted.');
  }
  await context.storageState({ path: './linkedin-session.json' });
  await browser.close();
})();
