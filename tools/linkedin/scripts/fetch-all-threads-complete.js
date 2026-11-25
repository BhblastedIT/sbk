#!/usr/bin/env node




















const fs = require('fs');
const path = require('path');




const safety = require('./li-safety.js');



const SESSION_FILE = process.env.LINKEDIN_SESSION || path.join(__dirname, '..', '..', '..', 'sbk', 'raw', 'linkedin', 'linkedin-session.json');
const OUTPUT_DIR = path.join(__dirname, '..', '..', '..', 'sbk', 'raw', 'linkedin');
const CHECKPOINT_DIR = path.join(OUTPUT_DIR, '.checkpoints');

const MY_URN = 'ACoAAEXAMPLE_URN_PLACEHOLDER';
const VOYAGER_BASE = 'https://www.linkedin.com/voyager/api';
const SALES_BASE = 'https://www.linkedin.com/sales-api';



const CONCURRENCY = 1;
const MAX_MESSAGES_PER_THREAD = 500;
const CHECKPOINT_EVERY = 20;




const guard = new safety.LinkedInSafetyGuard();



function loadSession() {
  if (!fs.existsSync(SESSION_FILE)) {
    console.error(`Session file not found: ${SESSION_FILE}`);
    console.error('Run login first or set LINKEDIN_SESSION env var.');
    process.exit(1);
  }
  const session = JSON.parse(fs.readFileSync(SESSION_FILE, 'utf8'));
  const li_at = session.cookies.find(c => c.name === 'li_at')?.value;
  const jsessionid = session.cookies.find(c => c.name === 'JSESSIONID')?.value;
  if (!li_at || !jsessionid) {
    console.error('Session missing li_at or JSESSIONID cookies. Re-login needed.');
    process.exit(1);
  }
  return { li_at, jsessionid, csrf: jsessionid.replace(/"/g, '') };
}

function makeHeaders(session, accept = 'application/vnd.linkedin.normalized+json+2.1') {
  return {
    'csrf-token': session.csrf,
    'cookie': `li_at=${session.li_at}; JSESSIONID=${session.jsessionid}`,
    'x-restli-protocol-version': '2.0.0',
    'x-li-lang': 'en_US',
    'accept': accept,
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'x-li-track': JSON.stringify({
      clientVersion: '1.13.42316', mpVersion: '1.13.42316', osName: 'web',
      timezoneOffset: 0, timezone: 'UTC', deviceFormFactor: 'DESKTOP',
      mpName: 'voyager-web', displayDensity: 1, displayWidth: 1280, displayHeight: 720,
    }),
  };
}



const delay = (ms) => new Promise(r => setTimeout(r, ms));
const encodeUrn = (urn) => urn.replace(/:/g, '%3A').replace(/\(/g, '%28').replace(/\)/g, '%29').replace(/,/g, '%2C').replace(/=/g, '%3D');
const ts = () => new Date().toISOString().substring(11, 19);

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function saveCheckpoint(name, data) {
  ensureDir(CHECKPOINT_DIR);
  fs.writeFileSync(path.join(CHECKPOINT_DIR, `${name}.json`), JSON.stringify(data));
}

function loadCheckpoint(name) {
  const fp = path.join(CHECKPOINT_DIR, `${name}.json`);
  if (fs.existsSync(fp)) return JSON.parse(fs.readFileSync(fp, 'utf8'));
  return null;
}














async function apiFetch(url, headers) {
  guard.resetTransientBackoff();

  for (;;) {

    guard.assertUnderCaps();

    let res = null;
    let bodyText = '';
    try {
      res = await fetch(url, { headers, redirect: 'manual' });
      guard.recordCall(); // count the effective LinkedIn call toward the budgets
      bodyText = await res.text();
    } catch (e) {

      guard.recordCall();
      res = null;
    }


    const verdict = guard.classifyResponse(res, bodyText);

    if (verdict === safety.OK) {
      try {
        return JSON.parse(bodyText);
      } catch (e) {

        return null;
      }
    }

    if (verdict === safety.GONE) {

      return null;
    }

    if (verdict === safety.TRANSIENT) {

      console.log(`  [${ts()}] Transient error, backing off...`);
      await guard.expBackoffTransient(); // throws after 3 attempts -> abort run
      continue;
    }


    return null;
  }
}



async function safeDelay() {
  await guard.randomDelay();
}





async function fetchStandardConversations(session) {
  console.log('\n' + '═'.repeat(60));
  console.log('  PART 1: LinkedIn Standard Inbox');
  console.log('═'.repeat(60) + '\n');

  const graphqlHeaders = makeHeaders(session, 'application/graphql');
  const normalizedHeaders = makeHeaders(session);


  const me = await apiFetch(`${VOYAGER_BASE}/me`, normalizedHeaders);
  if (!me) { console.error('Login failed!'); return null; }
  const myProfile = (me.included || []).find(e => e['$type']?.includes('MiniProfile'));
  console.log(`  Logged in as: ${myProfile?.firstName} ${myProfile?.lastName}\n`);


  console.log('  [1/3] Fetching conversation list...\n');

  const CONV_PAGE_SIZE = 50; // Conversations per page (was 20)

  async function fetchConvPage(category, cursor) {
    const mailbox = `urn%3Ali%3Afsd_profile%3A${MY_URN}`;
    const params = cursor
      ? `(query:(predicateUnions:List((conversationCategoryPredicate:(category:${category})))),count:${CONV_PAGE_SIZE},mailboxUrn:${mailbox},cursor:${cursor})`
      : `(query:(predicateUnions:List((conversationCategoryPredicate:(category:${category})))),count:${CONV_PAGE_SIZE},mailboxUrn:${mailbox})`;
    return apiFetch(
      `${VOYAGER_BASE}/voyagerMessagingGraphQL/graphql?queryId=messengerConversations.9501074288a12f3ae9e3c7ea243bccbf&variables=${params}`,
      graphqlHeaders
    );
  }

  async function fetchAllCategory(category) {
    const seenUrns = new Set();
    const convos = [];
    let cursor = null;
    let previousCursor = null;
    let staleCursorCount = 0;
    let page = 0;

    while (page < 300) {
      page++;
      const data = await fetchConvPage(category, cursor);
      const result = data?.data?.messengerConversationsByCategoryQuery || data?.data?.messengerConversationsBySyncToken || {};
      const elements = result.elements || [];

      let newCount = 0;
      for (const conv of elements) {
        const urn = conv.entityUrn || conv.backendUrn;
        if (urn && !seenUrns.has(urn)) {
          seenUrns.add(urn);
          convos.push(parseStandardConv(conv));
          newCount++;
        }
      }

      if (page % 10 === 0 || !result.metadata?.nextCursor) {
        console.log(`    [${category}] Page ${page}: +${newCount} (total: ${convos.length})`);
      }

      const newCursor = result.metadata?.nextCursor;


      if (newCursor && newCursor === previousCursor) {
        staleCursorCount++;
        if (staleCursorCount >= 3) {
          console.log(`    [${category}] Cursor stalled for 3 iterations, stopping pagination.`);
          break;
        }
      } else {
        staleCursorCount = 0;
      }

      previousCursor = cursor;
      cursor = newCursor;
      if (!cursor || elements.length === 0) break;
      await safeDelay();
    }
    return convos;
  }

  const primary = await fetchAllCategory('PRIMARY_INBOX');
  console.log();
  const secondary = await fetchAllCategory('SECONDARY_INBOX');


  const seenUrns = new Set();
  const allConvos = [];
  for (const conv of [...primary, ...secondary]) {
    if (!seenUrns.has(conv.entityUrn)) {
      seenUrns.add(conv.entityUrn);
      allConvos.push(conv);
    }
  }
  console.log(`\n  Total conversations: ${allConvos.length} (primary: ${primary.length}, secondary: ${secondary.length})`);


  console.log('\n  [2/3] Fetching full message threads...\n');

  const checkpoint = loadCheckpoint('standard-threads');
  const completedUrns = new Set(checkpoint?.completedUrns || []);
  let fetchedCount = 0;
  let totalMessages = 0;



  for (let i = 0; i < allConvos.length; i++) {
    const conv = allConvos[i];

    if (completedUrns.has(conv.entityUrn)) {

      const cached = checkpoint?.threads?.[conv.entityUrn];
      if (cached) conv.messages = cached;
      continue;
    }

    const messages = await fetchFullThread(conv.entityUrn, normalizedHeaders);
    conv.messages = messages;
    conv.totalMessages = messages.length;
    conv.mySentCount = messages.filter(m => m.senderIsMe).length;
    completedUrns.add(conv.entityUrn);
    fetchedCount += 1;

    if (fetchedCount % 10 === 0) {
      console.log(`    [${ts()}] ${fetchedCount}/${allConvos.length} threads fetched | ${allConvos.reduce((s, c) => s + (c.messages?.length || 0), 0)} total messages`);
    }


    if (fetchedCount % CHECKPOINT_EVERY === 0) {
      const threads = {};
      allConvos.filter(c => completedUrns.has(c.entityUrn)).forEach(c => { threads[c.entityUrn] = c.messages; });
      saveCheckpoint('standard-threads', { completedUrns: [...completedUrns], threads });
    }

    await safeDelay();
  }

  totalMessages = allConvos.reduce((s, c) => s + (c.messages?.length || 0), 0);
  const totalSent = allConvos.reduce((s, c) => s + (c.messages?.filter(m => m.senderIsMe).length || 0), 0);
  const totalReceived = totalMessages - totalSent;

  console.log(`\n  [3/3] Standard inbox complete!`);
  console.log(`    Conversations: ${allConvos.length}`);
  console.log(`    Total messages: ${totalMessages}`);
  console.log(`    Sent by you: ${totalSent}`);
  console.log(`    Received: ${totalReceived}`);

  return {
    source: 'linkedin-standard',
    fetchedAt: new Date().toISOString(),
    stats: {
      totalConversations: allConvos.length,
      totalMessages,
      sentByYou: totalSent,
      received: totalReceived,
    },
    conversations: allConvos,
  };
}

function parseStandardConv(conv) {
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
  }).filter(p => !p.urn.includes(MY_URN));

  const inlineMessages = (conv.messages?.elements || []).map(msg => ({
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
    participants,
    messages: inlineMessages,
    totalMessages: inlineMessages.length,
    mySentCount: inlineMessages.filter(m => m.senderIsMe).length,
  };
}

async function fetchFullThread(conversationUrn, headers) {
  const allMessages = [];
  const seenKeys = new Set();
  let cursor = null;
  let page = 0;

  while (page < 50) {
    page++;
    const encoded = encodeUrn(conversationUrn);
    const params = cursor
      ? `(conversationUrn:${encoded},count:40,cursor:${cursor})`
      : `(conversationUrn:${encoded},count:40)`;

    const data = await apiFetch(
      `${VOYAGER_BASE}/voyagerMessagingGraphQL/graphql?queryId=messengerMessages.5846eeb71c981f11e0134cb6626cc314&variables=${params}`,
      headers
    );

    if (!data) break;

    const included = data.included || data.data?.included || [];
    const messages = included.filter(i => i['$type'] === 'com.linkedin.messenger.Message');

    let newCount = 0;
    for (const msg of messages) {
      const key = `${msg.deliveredAt}|${(msg.body?.text || '').substring(0, 50)}`;
      if (!seenKeys.has(key)) {
        seenKeys.add(key);
        allMessages.push({
          senderIsMe: (msg['*sender'] || '').includes(MY_URN),
          body: msg.body?.text || '',
          deliveredAt: msg.deliveredAt ? new Date(msg.deliveredAt).toISOString() : null,
          subject: msg.subject || null,
        });
        newCount++;
      }
    }


    const metadata = data.data?.messengerMessagesByCriteria?.metadata
      || data.data?.messengerMessages?.metadata || {};
    cursor = metadata.previousCursor || metadata.nextCursor || null;

    if (!cursor || messages.length === 0 || allMessages.length >= MAX_MESSAGES_PER_THREAD) break;
    await safeDelay();
  }


  allMessages.sort((a, b) => (a.deliveredAt || '').localeCompare(b.deliveredAt || ''));
  return allMessages;
}





async function fetchSalesNavigatorConversations(session) {
  console.log('\n' + '═'.repeat(60));
  console.log('  PART 2: Sales Navigator Inbox');
  console.log('═'.repeat(60) + '\n');





  const snHeaders = makeHeaders(session);
  try {
    const accessCheck = await apiFetch(`${SALES_BASE}/salesApiProfiles?decoration=memberStatus`, snHeaders);
    if (!accessCheck) {
      console.log('  Sales Navigator not accessible (no subscription or expired). Skipping.');
      return null;
    }
  } catch (e) {
    console.log(`  Sales Navigator access check failed: ${e.message}. Skipping.`);
    return null;
  }







  if (process.env.LI_ALLOW_SN_BROWSER !== '1') {
    console.error('\n  ⛔ Sales Navigator phase (Playwright) DISABLED for safety.');
    console.error('     SPA navigation + scrolling = untracked request bursts → risk of account restriction.');
    console.error('     To force it (at your own risk): LI_ALLOW_SN_BROWSER=1 node fetch-all-threads-complete.js ...\n');
    return null;
  }

  let chromium;
  try {
    ({ chromium } = require('playwright'));
  } catch (e) {
    console.error('  Playwright is not installed. Install with: npm install playwright');
    console.error('  Sales Navigator requires the browser to intercept the APIs.');
    return null;
  }

  const browser = await chromium.launch({ headless: false, slowMo: 50 });
  const context = await browser.newContext({ storageState: SESSION_FILE });
  const page = await context.newPage();

  const conversationMap = new Map();
  const messageMap = new Map(); // conversationId -> messages[]


  page.on('response', async (response) => {
    const url = response.url();
    if (response.status() !== 200) return;

    try {

      if (url.includes('/sales-api/salesApiMessaging') || url.includes('/sales/inbox') || url.includes('messagingThread')) {
        const text = await response.text();
        const json = JSON.parse(text);


        if (json.elements) {
          for (const conv of json.elements) {
            const id = conv.entityUrn || conv.threadId || conv.conversationId || conv['$id'];
            if (id && !conversationMap.has(id)) {
              conversationMap.set(id, parseSalesNavConv(conv));
            }
          }
        }


        if (json.included) {
          for (const item of json.included) {
            if (item['$type']?.includes('Message') || item.body) {
              const threadId = item['*thread'] || item['*conversation'] || item.conversationUrn;
              if (threadId) {
                if (!messageMap.has(threadId)) messageMap.set(threadId, []);
                messageMap.get(threadId).push({
                  senderIsMe: isMySalesMessage(item),
                  body: item.body?.text || item.body || '',
                  deliveredAt: item.createdAt ? new Date(item.createdAt).toISOString() : null,
                  subject: item.subject || null,
                  type: item.messageType || 'standard',
                });
              }
            }
          }
        }


        if (json.data) {
          const elements = json.data.elements || json.data.results || json.data.conversations?.elements || [];
          for (const conv of elements) {
            const id = conv.entityUrn || conv.threadId || conv['$id'];
            if (id && !conversationMap.has(id)) {
              conversationMap.set(id, parseSalesNavConv(conv));
            }
          }
        }
      }
    } catch (e) { /* ignore parse errors */ }
  });


  console.log('  Opening Sales Navigator inbox...');
  await page.goto('https://www.linkedin.com/sales/inbox/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await delay(5000);


  const currentUrl = page.url();
  if (!currentUrl.includes('/sales/')) {
    console.log('  WARNING: Sales Navigator not accessible. An active subscription may be required.');
    console.log(`  Redirected to: ${currentUrl}`);
    await browser.close();
    return null;
  }

  console.log(`  Sales Navigator inbox loaded. Initial conversations: ${conversationMap.size}\n`);


  console.log('  [1/3] Scrolling to load all Sales Navigator conversations...\n');

  let prevCount = 0;
  let noNewCount = 0;
  let scrollAttempts = 0;

  while (scrollAttempts < 300) {
    scrollAttempts++;


    await page.evaluate(() => {
      const selectors = [
        '[class*="inbox-layout__conversation-list"]',
        '[class*="conversation-list-container"]',
        '[class*="message-list"]',
        'main [role="region"]',
        '.artdeco-list',
        'ul[role="list"]',
        'aside',
        'html',
      ];
      for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
          if (el.scrollHeight > el.clientHeight + 50) {
            el.scrollTop = el.scrollHeight;
          }
        }
      }

      document.querySelectorAll('[class*="scroll"], [class*="list"]').forEach(el => {
        if (el.scrollHeight > el.clientHeight + 100) el.scrollTop = el.scrollHeight;
      });
    });




    guard.assertUnderCaps();
    guard.recordCall();
    await safeDelay();

    const currentCount = conversationMap.size;
    if (currentCount > prevCount) {
      noNewCount = 0;
      if (scrollAttempts % 5 === 0) {
        console.log(`    Scroll ${scrollAttempts}: ${currentCount} conversations (+${currentCount - prevCount})`);
      }
    } else {
      noNewCount++;
    }
    prevCount = currentCount;

    if (noNewCount >= 12) {
      console.log(`    Reached end after ${scrollAttempts} scrolls.`);
      break;
    }
  }

  console.log(`\n  Conversations found: ${conversationMap.size}\n`);


  console.log('  [2/3] Loading full message threads...\n');

  const convList = [...conversationMap.values()];
  let threadsFetched = 0;


  const convElements = await page.$$('[class*="conversation-list-item"], [class*="inbox-entity"], li[class*="artdeco"]');
  console.log(`    Found ${convElements.length} clickable conversation elements`);

  for (const el of convElements) {
    try {


      guard.assertUnderCaps();
      await el.click();
      guard.recordCall();
      await safeDelay();


      await page.evaluate(() => {
        const msgContainers = document.querySelectorAll('[class*="message-thread"], [class*="conversation-detail"], [class*="message-list"]');
        msgContainers.forEach(el => el.scrollTop = 0); // scroll UP for older messages
      });
      await delay(800);

      threadsFetched++;
      if (threadsFetched % 20 === 0) {
        console.log(`    [${ts()}] ${threadsFetched} threads loaded | ${messageMap.size} with messages`);
      }
    } catch (e) {

      if (/cap reached|backoff exhausted/i.test(e && e.message ? e.message : '')) {
        throw e;
      }

    }
  }


  console.log(`\n  [3/3] Attempting direct Sales API fetch for remaining threads...\n`);

  const salesHeaders = makeHeaders(session);
  salesHeaders['x-li-page-instance'] = 'urn:li:page:sales_inbox;' + Date.now();

  for (const conv of convList) {
    if (messageMap.has(conv.entityUrn) && messageMap.get(conv.entityUrn).length > 0) continue;

    const encoded = encodeUrn(conv.entityUrn);
    const data = await apiFetch(
      `${SALES_BASE}/salesApiMessaging/messages?conversationUrn=${encoded}&count=100`,
      salesHeaders
    );

    if (data?.elements) {
      const msgs = data.elements.map(msg => ({
        senderIsMe: isMySalesMessage(msg),
        body: msg.body?.text || msg.body || '',
        deliveredAt: msg.createdAt ? new Date(msg.createdAt).toISOString() : null,
        subject: msg.subject || null,
        type: msg.messageType || 'standard',
      }));
      if (msgs.length > 0) messageMap.set(conv.entityUrn, msgs);
    }

    await safeDelay();
  }


  for (const conv of convList) {
    const msgs = messageMap.get(conv.entityUrn) || [];

    const seen = new Set();
    conv.messages = msgs.filter(m => {
      const key = `${m.deliveredAt}|${(m.body || '').substring(0, 50)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).sort((a, b) => (a.deliveredAt || '').localeCompare(b.deliveredAt || ''));

    conv.totalMessages = conv.messages.length;
    conv.mySentCount = conv.messages.filter(m => m.senderIsMe).length;
  }

  const totalMessages = convList.reduce((s, c) => s + c.messages.length, 0);
  const totalSent = convList.reduce((s, c) => s + c.mySentCount, 0);

  console.log(`\n  Sales Navigator inbox complete!`);
  console.log(`    Conversations: ${convList.length}`);
  console.log(`    Total messages: ${totalMessages}`);
  console.log(`    Sent by you: ${totalSent}`);
  console.log(`    Received: ${totalMessages - totalSent}`);


  await context.storageState({ path: SESSION_FILE });
  await browser.close();

  return {
    source: 'sales-navigator',
    fetchedAt: new Date().toISOString(),
    stats: {
      totalConversations: convList.length,
      totalMessages,
      sentByYou: totalSent,
      received: totalMessages - totalSent,
    },
    conversations: convList,
  };
}

function parseSalesNavConv(conv) {
  const participants = [];


  const participantData = conv.participants || conv.recipients || conv.conversationParticipants || [];
  for (const p of Array.isArray(participantData) ? participantData : [participantData]) {
    const name = p.name || p.firstName && `${p.firstName} ${p.lastName || ''}`.trim() || p.fullName || 'Unknown';
    const profileUrl = p.profileUrl || p.linkedInUrl || p.publicProfileUrl || '';
    const urn = p.entityUrn || p.hostIdentityUrn || p.urn || '';
    if (!urn.includes(MY_URN)) {
      participants.push({ name, profileUrl, urn });
    }
  }

  return {
    entityUrn: conv.entityUrn || conv.threadId || conv['$id'] || '',
    createdAt: conv.createdAt ? new Date(conv.createdAt).toISOString() : null,
    lastActivityAt: conv.lastActivityAt || conv.lastModifiedAt ? new Date(conv.lastActivityAt || conv.lastModifiedAt).toISOString() : null,
    participants,
    messages: [],
    totalMessages: 0,
    mySentCount: 0,
    isInMail: (conv.categories || []).includes('INMAIL') || (conv.mailboxItemType || '').includes('INMAIL'),
  };
}

function isMySalesMessage(msg) {
  const sender = msg['*sender'] || msg.sender?.entityUrn || msg.senderUrn || msg.sender || '';
  return sender.includes(MY_URN);
}





async function main() {
  const args = process.argv.slice(2);
  const doStandard = !args.includes('--sales-nav');
  const doSalesNav = !args.includes('--standard');
  const resume = args.includes('--resume');

  console.log('╔' + '═'.repeat(58) + '╗');
  console.log('║  SBK — LinkedIn Complete Thread Fetcher              ║');
  console.log('║  Standard Inbox + Sales Navigator                       ║');
  console.log('╚' + '═'.repeat(58) + '╝\n');



  safety.checkKillswitch();
  console.log(
    `  [safety] session cap ${guard.sessionCap} | daily cap ${guard.dailyCap} | ` +
      `used today ${safety.loadDailyCap()} | delay ${safety.MIN_DELAY_MS / 1000}-${safety.MAX_DELAY_MS / 1000}s\n`
  );

  const session = loadSession();
  ensureDir(OUTPUT_DIR);

  let standardResult = null;
  let salesNavResult = null;


  if (doStandard) {
    standardResult = await fetchStandardConversations(session);
    if (standardResult) {
      const outFile = path.join(OUTPUT_DIR, 'linkedin-threads-standard.json');
      fs.writeFileSync(outFile, JSON.stringify(standardResult, null, 2));
      console.log(`\n  Saved → ${outFile}\n`);
    }
  }


  if (doSalesNav) {
    salesNavResult = await fetchSalesNavigatorConversations(session);
    if (salesNavResult) {
      const outFile = path.join(OUTPUT_DIR, 'linkedin-threads-sales-navigator.json');
      fs.writeFileSync(outFile, JSON.stringify(salesNavResult, null, 2));
      console.log(`\n  Saved → ${outFile}\n`);
    }
  }


  console.log('\n' + '═'.repeat(60));
  console.log('  FINAL SUMMARY');
  console.log('═'.repeat(60));

  if (standardResult) {
    console.log(`\n  LinkedIn Standard Inbox:`);
    console.log(`    Conversations: ${standardResult.stats.totalConversations}`);
    console.log(`    Total messages: ${standardResult.stats.totalMessages}`);
    console.log(`    Sent: ${standardResult.stats.sentByYou} | Received: ${standardResult.stats.received}`);
  }

  if (salesNavResult) {
    console.log(`\n  Sales Navigator Inbox:`);
    console.log(`    Conversations: ${salesNavResult.stats.totalConversations}`);
    console.log(`    Total messages: ${salesNavResult.stats.totalMessages}`);
    console.log(`    Sent: ${salesNavResult.stats.sentByYou} | Received: ${salesNavResult.stats.received}`);
  }

  const totalConvs = (standardResult?.stats.totalConversations || 0) + (salesNavResult?.stats.totalConversations || 0);
  const totalMsgs = (standardResult?.stats.totalMessages || 0) + (salesNavResult?.stats.totalMessages || 0);
  console.log(`\n  TOTAL: ${totalConvs} conversations, ${totalMsgs} messages`);
  console.log('═'.repeat(60) + '\n');


  if (fs.existsSync(CHECKPOINT_DIR)) {
    fs.rmSync(CHECKPOINT_DIR, { recursive: true });
    console.log('  Checkpoints cleaned up.\n');
  }
}

main().catch(e => {
  const msg = e && e.message ? e.message : String(e);



  if (/cap reached|backoff exhausted/i.test(msg)) {
    console.log(`\n[safety] Run halted by policy: ${msg}`);
    console.log('[safety] Progress is checkpointed; resume later within the daily budget.');
    process.exit(0);
  }
  console.error('\nFATAL:', msg);
  process.exit(1);
});
