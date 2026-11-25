#!/usr/bin/env node































'use strict';

const { chromium } = require('playwright');
const fs = require('fs');

const safety = require('./li-safety.js');
const {
  LinkedInSafetyGuard,
  checkKillswitch,
  tripKillswitch,
  DEFAULT_SESSION_CAP,
} = safety;

const LINKEDIN_STORAGE = './linkedin-session.json';
const MY_URN = 'ACoAAEXAMPLE_URN_PLACEHOLDER';
const OUTPUT_FILE = './data/linkedin/linkedin-all-conversations-raw.json';





const DEFAULT_MAX_SCROLLS = 12;       // was 400 (excessive). Conservative default.




const SCRAPE_SESSION_CAP = Math.min(12, DEFAULT_SESSION_CAP);




const PAGE_RESTRICTION_MARKERS = [
  'temporarily restricted',
  'unusual activity',
  'software that automates activity',
  'captcha',
  'challenge',
  'visiting a very high number of pages',
  'request denied',
];

const PAGE_URL_PATTERNS = [
  /\/authwall/i,
  /\/checkpoint/i,
  /\/challenge/i,
  /\/uas\/login/i,
  /\/login/i,
];




function parseArgs(argv) {
  const args = { run: false, maxScrolls: DEFAULT_MAX_SCROLLS, sessionCap: SCRAPE_SESSION_CAP };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--run') args.run = true;
    else if (a === '--max-scrolls') args.maxScrolls = parseInt(argv[++i], 10);
    else if (a === '--session-cap') args.sessionCap = parseInt(argv[++i], 10);
  }

  if (!Number.isFinite(args.maxScrolls) || args.maxScrolls < 1) args.maxScrolls = DEFAULT_MAX_SCROLLS;
  if (args.maxScrolls > DEFAULT_MAX_SCROLLS) args.maxScrolls = DEFAULT_MAX_SCROLLS; // never raise above conservative default
  if (!Number.isFinite(args.sessionCap) || args.sessionCap < 1) args.sessionCap = SCRAPE_SESSION_CAP;
  return args;
}

function parseGraphqlConversation(conv) {
  const participants = (conv.conversationParticipants || []).map(p => {
    const member = p?.participantType?.member;
    if (member) {
      return {
        name: `${member.firstName?.text || ''} ${member.lastName?.text || ''}`.trim(),
        profileUrl: member.profileUrl || '',
        urn: p.hostIdentityUrn || '',
      };
    }
    return { name: 'Unknown', urn: p?.hostIdentityUrn || '' };
  });

  const otherParticipants = participants.filter(p => !p.urn.includes(MY_URN));

  const messages = (conv.messages?.elements || []).map(msg => ({
    senderIsMe: (msg.sender?.hostIdentityUrn || '').includes(MY_URN),
    body: msg.body?.text || '',
    deliveredAt: msg.deliveredAt ? new Date(msg.deliveredAt).toISOString() : null,
    subject: msg.subject || null,
  }));

  return {
    entityUrn: conv.entityUrn || conv.backendUrn || '',
    backendUrn: conv.backendUrn || '',
    createdAt: conv.createdAt ? new Date(conv.createdAt).toISOString() : null,
    lastActivityAt: conv.lastActivityAt ? new Date(conv.lastActivityAt).toISOString() : null,
    categories: conv.categories || [],
    participants: otherParticipants,
    inlineMessages: messages,
    hasMySentMessage: messages.some(m => m.senderIsMe),
  };
}

(async () => {
  const args = parseArgs(process.argv.slice(2));


  checkKillswitch();



  let guard;
  try {
    guard = new LinkedInSafetyGuard({ sessionCap: args.sessionCap });
  } catch (e) {
    process.stderr.write(`[scrape-all-conversations] ${e.message}\n`);
    process.exit(1);
  }

  console.log('=== scrape-all-conversations (hardened) ===');
  console.log(`  plan: up to ${args.maxScrolls} scroll batches, session cap ${guard.sessionCap}`);
  console.log('  delay between significant scrolls: jittered 45-120s (shared policy)');
  console.log('  daily cap: shared 40/day across all LinkedIn scripts');


  if (!args.run) {
    console.log('\nDRY RUN: no browser launched, no LinkedIn call made.');
    console.log('Re-run with --run to actually scrape (conservative limits apply).');
    return;
  }

  const conversationMap = new Map();

  const browser = await chromium.launch({ headless: false, slowMo: 50 });
  const context = await browser.newContext({ storageState: LINKEDIN_STORAGE });
  const page = await context.newPage();




  page.on('response', async response => {
    const url = response.url();
    const isMessaging = url.includes('voyagerMessagingGraphQL') || url.includes('messengerConversation');
    const isLinkedinDoc = url.includes('linkedin.com') &&
      (url.includes('/messaging') || PAGE_URL_PATTERNS.some(p => p.test(url)));
    if (!isMessaging && !isLinkedinDoc) return;

    let text = '';
    try {
      text = await response.text();
    } catch (e) {
      text = '';
    }



    try {
      guard.classifyResponse({ status: response.status(), url }, text);
    } catch (e) {

    }

    if (!isMessaging) return;
    if (response.status() !== 200) return;

    try {
      const json = JSON.parse(text);
      if (json.data) {
        const queryResult = json.data.messengerConversationsByCategoryQuery
          || json.data.messengerConversationsBySyncToken
          || json.data.messengerConversationsById
          || null;

        if (queryResult?.elements) {
          let newCount = 0;
          for (const conv of queryResult.elements) {
            const urn = conv.entityUrn || conv.backendUrn;
            if (urn && !conversationMap.has(urn)) {
              conversationMap.set(urn, parseGraphqlConversation(conv));
              newCount++;
            }
          }
          if (newCount > 0) {
            console.log(`  [API] +${newCount} new (total: ${conversationMap.size})`);
          }
        }
      }
    } catch (e) {}
  });



  async function assertPageNotRestricted() {
    let pageUrl = '';
    let bodyText = '';
    try { pageUrl = page.url(); } catch (e) {}
    for (const pat of PAGE_URL_PATTERNS) {
      if (pat.test(pageUrl)) {
        tripKillswitch(`Page navigated to authwall/checkpoint/challenge: ${pageUrl}`);
      }
    }
    try {
      bodyText = (await page.evaluate(() => (document.body && document.body.innerText) || '')).toLowerCase();
    } catch (e) {
      bodyText = '';
    }
    for (const marker of PAGE_RESTRICTION_MARKERS) {
      if (bodyText.indexOf(marker) !== -1) {
        tripKillswitch(`Restriction/challenge marker on page: '${marker}'`);
      }
    }
  }

  try {
    console.log('\nOpening LinkedIn Messaging...');
    guard.assertUnderCaps();
    await page.goto('https://www.linkedin.com/messaging/', { waitUntil: 'domcontentloaded' });
    guard.recordCall(); // count the navigation toward the shared daily budget
    await page.waitForTimeout(6000);
    await assertPageNotRestricted();
    console.log(`Initial load: ${conversationMap.size} conversations\n`);

    console.log('Scrolling to load conversations (conservative, jittered)...\n');

    let previousCount = 0;
    let noNewCount = 0;

    for (let scrollAttempts = 1; scrollAttempts <= args.maxScrolls; scrollAttempts++) {

      try {
        guard.assertUnderCaps();
      } catch (e) {
        console.log(`  ${e.message}`);
        break;
      }


      await assertPageNotRestricted();

      await page.evaluate(() => {
        const selectors = [
          '.msg-conversations-container__conversations-list',
          '[class*="msg-conversations-container"]',
          '.scaffold-layout__list',
          'ul[class*="msg-conversations"]',
        ];
        for (const sel of selectors) {
          const el = document.querySelector(sel);
          if (el && el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight;
        }
      });

      guard.recordCall(); // each scroll batch triggers page fetches -> count it


      const delay = await guard.randomDelay();
      console.log(`  scroll ${scrollAttempts}/${args.maxScrolls}: waited ${Math.round(delay / 1000)}s, ${conversationMap.size} conversations`);

      await assertPageNotRestricted();

      const currentCount = conversationMap.size;
      if (currentCount > previousCount) {
        noNewCount = 0;
      } else {
        noNewCount++;
      }
      previousCount = currentCount;


      if (noNewCount >= 3) {
        console.log(`  No new conversations after ${noNewCount} batches. Stopping.`);
        break;
      }
    }

    console.log(`\nScrolling complete: ${conversationMap.size} conversations\n`);

    const allConvos = [...conversationMap.values()];
    const withMySent = allConvos.filter(c => c.hasMySentMessage);

    const output = {
      fetchedAt: new Date().toISOString(),
      stats: {
        totalConversations: allConvos.length,
        withInlineMessages: allConvos.filter(c => c.inlineMessages.length > 0).length,
        withMySentMessage: withMySent.length,
      },
      conversations: allConvos,
    };

    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
    console.log(`SAVED ${allConvos.length} conversations to ${OUTPUT_FILE}`);
    console.log(`  ${withMySent.length} have at least one sent message in inline data`);
    console.log(`  ${allConvos.filter(c => c.inlineMessages.length > 0).length} have inline messages`);

    await context.storageState({ path: LINKEDIN_STORAGE });
  } finally {
    await browser.close();
  }

  console.log('\nDone. Run fetch-conversation-messages.js for full messages (also rate-limited).');
})();
