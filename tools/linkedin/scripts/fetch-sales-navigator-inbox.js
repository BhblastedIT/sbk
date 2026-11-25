#!/usr/bin/env node















const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');



const safety = require('./li-safety.js');
const { LinkedInSafetyGuard, OK, GONE, TRANSIENT } = safety;

const OUTPUT_DIR = path.join(__dirname, '..', '..', '..', 'sbk', 'raw', 'linkedin');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'linkedin-threads-sales-navigator.json');
const CHECKPOINT_FILE = path.join(OUTPUT_DIR, '.sn-threads-checkpoint.json');
const SESSION_FILE = process.env.LINKEDIN_SESSION || path.join(OUTPUT_DIR, 'linkedin-session.json');

const MY_URN = 'ACoAAEXAMPLE_URN_PLACEHOLDER';

const delay = (ms) => new Promise(r => setTimeout(r, ms));
const ts = () => new Date().toISOString().substring(11, 19);






const MASS_PULL_CONFIRM_FLAG = '--confirm-mass-pull';

function requireMassPullConfirmation() {
  if (!process.argv.includes(MASS_PULL_CONFIRM_FLAG)) {
    process.stderr.write(
      '\n[fetch-sales-navigator-inbox] BLOCKED: high-risk Sales Navigator mass pull.\n' +
        '  This script paginates the /sales-api/salesApiMessagingThreads family,\n' +
        '  an endpoint family known to trigger account restrictions.\n' +
        '  It is conservative-by-default and refuses to run unmonitored.\n\n' +
        `  To run anyway (you accept the risk and will watch it): pass ${MASS_PULL_CONFIRM_FLAG}\n` +
        '  Safety policy in force when confirmed:\n' +
        '    - delay 45-120s between calls (jittered)\n' +
        '    - session cap 30 calls, daily cap 40 calls (shared cross-script)\n' +
        '    - kill-switch on first 429/999/authwall/challenge -> hard STOP\n\n'
    );
    process.exit(3);
  }
  process.stderr.write(
    `[fetch-sales-navigator-inbox] ${MASS_PULL_CONFIRM_FLAG} present. ` +
      'Proceeding under conservative safety policy (45-120s delay, caps 30/40, kill-switch).\n'
  );
}



const THREAD_DECORATION_ENCODED =
  '%28id%2Crestrictions%2Carchived%2CunreadMessageCount%2CnextPageStartsAt%2CtotalMessageCount%2C' +
  'messages*%28id%2Ctype%2CcontentFlag%2CdeliveredAt%2ClastEditedAt%2Csubject%2Cbody%2CfooterText%2CblockCopy%2Cattachments%2Cauthor%2CsystemMessageContent%29%2C' +
  'participants*~fs_salesProfile%28entityUrn%2CfirstName%2ClastName%2CfullName%2Cdegree%2CprofilePictureDisplayImage%2CobjectUrn%2CinmailRestriction%29%29';



function loadCheckpoint() {
  if (fs.existsSync(CHECKPOINT_FILE)) {
    return JSON.parse(fs.readFileSync(CHECKPOINT_FILE, 'utf8'));
  }
  return { threads: [], profiles: {}, lastPageStartsAt: null, phase: 'list' };
}

function saveCheckpoint(checkpoint) {
  fs.writeFileSync(CHECKPOINT_FILE, JSON.stringify(checkpoint));
}



(async () => {
  const resume = process.argv.includes('--resume');

  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║  SBK — Sales Navigator Inbox (Hybrid)                ║');
  console.log('║  Browser auth + API fetch for full thread data          ║');
  console.log('╚══════════════════════════════════════════════════════════╝\n');


  requireMassPullConfirmation();




  const guard = new LinkedInSafetyGuard();

  if (!fs.existsSync(SESSION_FILE)) {
    console.error(`Session file not found: ${SESSION_FILE}`);
    process.exit(1);
  }

  const browser = await chromium.launch({
    headless: false,
    args: ['--window-size=1400,900'],
  });

  const context = await browser.newContext({
    storageState: SESSION_FILE,
    viewport: { width: 1400, height: 900 },
  });

  const page = await context.newPage();



  console.log('  [1/4] Opening Sales Navigator inbox...');
  await page.goto('https://www.linkedin.com/sales/inbox/', {
    waitUntil: 'domcontentloaded',
    timeout: 30000,
  });
  await delay(5000);

  const currentUrl = page.url();
  if (!currentUrl.includes('/sales/')) {
    console.log(`\n  WARNING: Not on Sales Navigator. URL: ${currentUrl}`);
    console.log('  Waiting for manual login (120s timeout)...');
    await page.waitForURL('**/sales/**', { timeout: 120000 }).catch(() => {});
    await delay(3000);
  }

  console.log(`  SN inbox loaded: ${currentUrl}\n`);


  const csrfToken = await page.evaluate(() => {
    const match = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
    return match ? match[1].replace(/"/g, '') : null;
  });

  if (!csrfToken) {
    console.error('  Could not extract CSRF token from cookies!');
    await browser.close();
    process.exit(1);
  }
  console.log(`  CSRF token extracted: ${csrfToken.substring(0, 20)}...\n`);



  console.log('  [2/4] Fetching all conversation threads via API...\n');

  let checkpoint = resume ? loadCheckpoint() : { threads: [], profiles: {}, lastPageStartsAt: null, phase: 'list' };
  let allThreads = checkpoint.threads || [];
  const profileMap = checkpoint.profiles || {};
  let pageStartsAt = checkpoint.lastPageStartsAt || Date.now();
  let pageNum = allThreads.length > 0 ? Math.floor(allThreads.length / 20) : 0;
  let emptyPages = 0;


  const rateLimitCount = 0;
  const seenThreadIds = new Set(allThreads.map(t => t.threadId));

  if (allThreads.length > 0) {
    console.log(`  Resuming: ${allThreads.length} threads already fetched\n`);
  }



  while (pageNum < 500) {

    try {
      guard.assertUnderCaps();
    } catch (e) {
      console.log(`  [${ts()}] ${e.message}`);
      break;
    }

    pageNum++;




    const apiUrl = `/sales-api/salesApiMessagingThreads?decoration=${THREAD_DECORATION_ENCODED}&count=20&filter=INBOX&pageStartsAt=${pageStartsAt}&q=filter`;

    const raw = await page.evaluate(async ({ url, csrf }) => {
      try {
        const res = await fetch(url, {
          credentials: 'include',
          redirect: 'manual',
          headers: {
            'accept': 'application/json',
            'csrf-token': csrf,
            'x-restli-protocol-version': '2.0.0',
          },
        });
        const text = await res.text();
        return { status: res.status, url: res.url, body: text };
      } catch (e) {

        return { status: null, url, body: '', netError: String(e && e.message || e) };
      }
    }, { url: apiUrl, csrf: csrfToken });


    guard.recordCall();




    const verdict = guard.classifyResponse(
      { status: raw.status, url: raw.url },
      raw.body
    );

    if (verdict === TRANSIENT) {

      try {
        const waited = await guard.expBackoffTransient();
        console.log(`  [${ts()}] Transient (${raw.netError || raw.status}); backoff ${Math.round(waited / 1000)}s`);
      } catch (e) {
        console.log(`  [${ts()}] ${e.message}`);
        break;
      }
      continue;
    }

    if (verdict === GONE) {
      console.log(`  [${ts()}] Resource gone (status ${raw.status}); skipping page.`);
      emptyPages++;
      if (emptyPages > 5) break;
      await guard.randomDelay();
      continue;
    }


    guard.resetTransientBackoff();
    let result;
    try {
      result = raw.body ? JSON.parse(raw.body) : {};
    } catch (e) {
      console.log(`  [${ts()}] Could not parse JSON body; skipping page.`);
      emptyPages++;
      if (emptyPages > 5) break;
      await guard.randomDelay();
      continue;
    }


    const elements = result.data?.elements || result.elements || [];
    if (elements.length === 0) {
      emptyPages++;
      if (emptyPages > 3) {
        console.log(`  [${ts()}] No more conversations (${emptyPages} empty pages).`);
        break;
      }
      await guard.randomDelay();
      continue;
    }
    emptyPages = 0;

    let oldestTimestamp = Infinity;
    let newThreads = 0;

    for (const thread of elements) {
      const threadId = thread.id;
      if (!threadId || seenThreadIds.has(threadId)) continue;
      seenThreadIds.add(threadId);
      newThreads++;

      const messages = (thread.messages || []).map(msg => ({
        id: msg.id,
        body: msg.body || '',
        subject: msg.subject || null,
        deliveredAt: msg.deliveredAt ? new Date(msg.deliveredAt).toISOString() : null,
        deliveredAtRaw: msg.deliveredAt,
        author: msg.author || null,
        type: msg.type || 'STANDARD',
        contentFlag: msg.contentFlag || null,
        attachments: (msg.attachments || []).length > 0 ? msg.attachments : undefined,
      }));


      const participantUrns = (thread.participants || []).filter(p => typeof p === 'string');


      const resolved = thread.participantsResolutionResults || {};
      for (const [urn, profile] of Object.entries(resolved)) {
        if (profile.fullName || profile.firstName) {
          profileMap[urn] = {
            firstName: profile.firstName || '',
            lastName: profile.lastName || '',
            fullName: profile.fullName || `${profile.firstName || ''} ${profile.lastName || ''}`.trim(),
            objectUrn: profile.objectUrn || '',
            entityUrn: profile.entityUrn || urn,
          };
        }
      }

      allThreads.push({
        threadId,
        archived: thread.archived || false,
        totalMessageCount: thread.totalMessageCount || messages.length,
        unreadMessageCount: thread.unreadMessageCount || 0,
        participantUrns,
        messages,
      });


      for (const msg of messages) {
        if (msg.deliveredAtRaw && msg.deliveredAtRaw < oldestTimestamp) {
          oldestTimestamp = msg.deliveredAtRaw;
        }
      }
    }

    const totalMsgs = allThreads.reduce((s, t) => s + t.messages.length, 0);
    console.log(`  [${ts()}] Page ${pageNum}: +${newThreads} new (total: ${allThreads.length}) | ${totalMsgs} msgs | ${Object.keys(profileMap).length} profiles`);


    if (oldestTimestamp < Infinity) {
      pageStartsAt = oldestTimestamp - 1;
    } else {

      const lastThread = allThreads[allThreads.length - 1];
      const lastMsg = lastThread?.messages?.[0];
      if (lastMsg?.deliveredAtRaw) {
        pageStartsAt = lastMsg.deliveredAtRaw - 1;
      } else {
        break;
      }
    }


    if (pageNum % 5 === 0) {
      checkpoint = { threads: allThreads, profiles: profileMap, lastPageStartsAt: pageStartsAt, phase: 'list' };
      saveCheckpoint(checkpoint);
    }


    await guard.randomDelay();
  }

  console.log(`\n  Conversation list complete: ${allThreads.length} threads\n`);



  console.log('  [3/4] Expanding threads with more messages...\n');

  const threadsNeedingExpansion = allThreads.filter(t =>
    t.totalMessageCount > t.messages.length
  );

  console.log(`  ${threadsNeedingExpansion.length} threads need expansion\n`);

  let errors = 0;
  const expandStart = Date.now();



  let capReached = false;

  for (let i = 0; i < threadsNeedingExpansion.length && !capReached; i++) {
    const thread = threadsNeedingExpansion[i];
    const threadId = thread.threadId;

    try {
      const allMessages = [];
      const seenIds = new Set(thread.messages.map(m => m.id));
      let nextPage = thread.messages.length > 0
        ? Math.min(...thread.messages.map(m => m.deliveredAtRaw).filter(Boolean))
        : null;
      let fetchPages = 0;


      allMessages.push(...thread.messages);

      while (fetchPages < 20 && nextPage) {

        try {
          guard.assertUnderCaps();
        } catch (e) {
          console.log(`  [${ts()}] ${e.message}`);
          capReached = true;
          break;
        }

        fetchPages++;
        const expandUrl = `/sales-api/salesApiMessagingThreads/${encodeURIComponent(threadId)}?decoration=${THREAD_DECORATION_ENCODED}&count=1&messageCount=40&messagesNextPageStartsAt=${nextPage}`;

        const raw = await page.evaluate(async ({ url, csrf }) => {
          try {
            const res = await fetch(url, {
              credentials: 'include',
              redirect: 'manual',
              headers: {
                'accept': 'application/json',
                'csrf-token': csrf,
                'x-restli-protocol-version': '2.0.0',
              },
            });
            const text = await res.text();
            return { status: res.status, url: res.url, body: text };
          } catch (e) {
            return { status: null, url, body: '', netError: String(e && e.message || e) };
          }
        }, { url: expandUrl, csrf: csrfToken });



        guard.recordCall();
        const verdict = guard.classifyResponse({ status: raw.status, url: raw.url }, raw.body);

        if (verdict === TRANSIENT) {
          try {
            const waited = await guard.expBackoffTransient();
            console.log(`  [${ts()}] Transient during expand; backoff ${Math.round(waited / 1000)}s`);
            continue;
          } catch (e) {
            console.log(`  [${ts()}] ${e.message}`);
            capReached = true; // abort the whole expansion phase
            break;
          }
        }
        if (verdict === GONE) break;

        guard.resetTransientBackoff();
        let result;
        try {
          result = raw.body ? JSON.parse(raw.body) : {};
        } catch (e) { break; }

        const threadData = result.data || result;
        const messages = threadData.messages || [];
        if (messages.length === 0) break;

        let newCount = 0;
        let oldestTs = Infinity;

        for (const msg of messages) {
          const id = msg.id || `${msg.deliveredAt}|${(msg.body || '').substring(0, 50)}`;
          if (!seenIds.has(id)) {
            seenIds.add(id);
            allMessages.push({
              id: msg.id,
              body: msg.body || '',
              subject: msg.subject || null,
              deliveredAt: msg.deliveredAt ? new Date(msg.deliveredAt).toISOString() : null,
              deliveredAtRaw: msg.deliveredAt,
              author: msg.author || null,
              type: msg.type || 'STANDARD',
              contentFlag: msg.contentFlag || null,
              attachments: (msg.attachments || []).length > 0 ? msg.attachments : undefined,
            });
            newCount++;
          }
          if (msg.deliveredAt && msg.deliveredAt < oldestTs) {
            oldestTs = msg.deliveredAt;
          }
        }

        if (newCount === 0) break;
        nextPage = oldestTs < Infinity ? oldestTs : null;

        await guard.randomDelay();
      }


      allMessages.sort((a, b) => (a.deliveredAt || '').localeCompare(b.deliveredAt || ''));
      thread.messages = allMessages;

    } catch (e) {
      errors++;
    }


    if ((i + 1) % 10 === 0 || i === threadsNeedingExpansion.length - 1) {
      const elapsed = ((Date.now() - expandStart) / 1000).toFixed(0);
      console.log(`  [${ts()}] ${i + 1}/${threadsNeedingExpansion.length} expanded | ${errors} errors | ${elapsed}s`);
    }


    if ((i + 1) % 50 === 0) {
      checkpoint = { threads: allThreads, profiles: profileMap, phase: 'expand' };
      saveCheckpoint(checkpoint);
    }
  }



  console.log('\n  [4/4] Building output...\n');



  // Your name, from sbk.config.json "owner" (the same file and search order as tools/sbk_config.py).
  function readOwnerName() {
    const home = require('os').homedir();
    const dataRoot = process.env.SBK_DATA_ROOT || path.join(home, '.sbk-data');
    const candidates = [
      process.env.SBK_CONFIG,
      path.join(dataRoot, 'sbk.config.json'),
      path.join(__dirname, '..', '..', '..', 'sbk.config.json'),
    ];
    for (const c of candidates) {
      if (!c || !fs.existsSync(c)) continue;
      try {
        return String(JSON.parse(fs.readFileSync(c, 'utf8')).owner || '').trim();
      } catch (e) {
        console.warn(`  sbk.config unreadable (${c}): ${e.message}`);
      }
    }
    return '';
  }
  const OWNER_NAME = readOwnerName();
  if (!OWNER_NAME) {
    console.warn('  sbk.config.json has no "owner": your own profile cannot be recognised in the threads');
  }
  const OWNER_FIRST_NAME = OWNER_NAME ? OWNER_NAME.split(' ')[0].toLowerCase() : '';

  let mySNUrns = new Set();
  for (const [urn, profile] of Object.entries(profileMap)) {
    if (OWNER_NAME && (profile.fullName?.toLowerCase().includes(OWNER_NAME.toLowerCase()) ||
        profile.firstName?.toLowerCase() === OWNER_FIRST_NAME)) {
      mySNUrns.add(urn);
      console.log(`  Found my SN URN: ${urn} (${profile.fullName})`);
    }
  }



  const MY_MEMBER_PATTERN = process.env.LI_MY_MEMBER_PATTERN || 'EXAMPLE';

  function isMyUrn(urn) {
    if (!urn) return false;
    if (mySNUrns.has(urn)) return true;
    return urn.includes(MY_MEMBER_PATTERN);
  }

  console.log(`  Profile map size: ${Object.keys(profileMap).length}`);
  console.log(`  My SN URNs detected: ${mySNUrns.size}\n`);

  const conversations = allThreads.map(thread => {

    const participantUrns = thread.participantUrns || [];
    const otherParticipants = participantUrns
      .filter(urn => !isMyUrn(urn))
      .map(urn => {
        const profile = profileMap[urn];
        return profile
          ? { name: profile.fullName, entityUrn: profile.entityUrn, objectUrn: profile.objectUrn }
          : { name: 'Unknown', entityUrn: urn };
      });

    const messages = thread.messages.map(msg => {
      const author = msg.author || '';
      const senderIsMe = isMyUrn(author);
      const senderProfile = profileMap[author];
      return {
        senderIsMe,
        senderName: senderIsMe
          ? OWNER_NAME
          : (senderProfile?.fullName || otherParticipants[0]?.name || 'Unknown'),
        body: msg.body,
        subject: msg.subject,
        deliveredAt: msg.deliveredAt,
        type: msg.type,
        author: author || undefined,
      };
    });

    return {
      threadId: thread.threadId,
      archived: thread.archived,
      declaredMessageCount: thread.totalMessageCount,
      participants: otherParticipants,
      totalMessages: messages.length,
      mySentCount: messages.filter(m => m.senderIsMe).length,
      messages,
    };
  });


  conversations.sort((a, b) => {
    const aLast = a.messages[a.messages.length - 1]?.deliveredAt || '';
    const bLast = b.messages[b.messages.length - 1]?.deliveredAt || '';
    return bLast.localeCompare(aLast);
  });

  const totalMsgs = conversations.reduce((s, c) => s + c.totalMessages, 0);
  const totalSent = conversations.reduce((s, c) => s + c.mySentCount, 0);
  const withMsgs = conversations.filter(c => c.totalMessages > 0).length;

  const output = {
    source: 'sales-navigator',
    fetchedAt: new Date().toISOString(),
    stats: {
      totalConversations: conversations.length,
      conversationsWithMessages: withMsgs,
      totalMessages: totalMsgs,
      sentByYou: totalSent,
      received: totalMsgs - totalSent,
      profilesCaptured: Object.keys(profileMap).length,
      errors,
      rateLimitsHit: rateLimitCount,
    },
    conversations,
  };

  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
  console.log(`  Saved -> ${OUTPUT_FILE}`);
  console.log(`  Size: ${(fs.statSync(OUTPUT_FILE).size / 1024 / 1024).toFixed(1)} MB\n`);


  if (fs.existsSync(CHECKPOINT_FILE)) fs.unlinkSync(CHECKPOINT_FILE);


  await context.storageState({ path: SESSION_FILE });


  console.log('='.repeat(60));
  console.log('  SALES NAVIGATOR INBOX - COMPLETED');
  console.log('='.repeat(60));
  console.log(`  Conversations: ${conversations.length}`);
  console.log(`  With messages: ${withMsgs}`);
  console.log(`  Total messages: ${totalMsgs}`);
  console.log(`  Sent by you: ${totalSent}`);
  console.log(`  Received: ${totalMsgs - totalSent}`);
  console.log(`  Profiles: ${Object.keys(profileMap).length}`);
  console.log(`  Errors: ${errors}`);
  console.log(`  Rate limits: ${rateLimitCount}`);
  console.log('='.repeat(60) + '\n');

  await browser.close();
})();
