#!/usr/bin/env node






























const fs = require('fs');
const path = require('path');


const safety = require('./li-safety.js');
const { LinkedInSafetyGuard } = safety;

const OUTPUT_DIR = path.join(__dirname, '..', '..', 'sbk', 'raw', 'linkedin');
const INPUT_FILE = path.join(OUTPUT_DIR, 'linkedin-all-conversations-raw.json');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'linkedin-threads-complete.json');
const CHECKPOINT_FILE = path.join(OUTPUT_DIR, '.threads-checkpoint.json');
const SESSION_FILE = path.join(OUTPUT_DIR, 'linkedin-session.json');

const MY_URN = 'ACoAAEXAMPLE_URN_PLACEHOLDER';
const BASE = 'https://www.linkedin.com/voyager/api';


const CONCURRENCY = 1;
const MAX_MESSAGES_PER_THREAD = 200;
const MAX_PAGES_PER_THREAD = 20;



const session = JSON.parse(fs.readFileSync(SESSION_FILE, 'utf8'));
const li_at = session.cookies.find(c => c.name === 'li_at').value;
const jsessionid = session.cookies.find(c => c.name === 'JSESSIONID').value;
const csrf = jsessionid.replace(/"/g, '');

const headers = {
  'csrf-token': csrf,
  'cookie': `li_at=${li_at}; JSESSIONID=${jsessionid}`,
  'x-restli-protocol-version': '2.0.0',
  'x-li-lang': 'en_US',
  'accept': 'application/vnd.linkedin.normalized+json+2.1',
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  'x-li-track': JSON.stringify({
    clientVersion: '1.13.42316', mpVersion: '1.13.42316', osName: 'web',
    timezoneOffset: 0, timezone: 'UTC', deviceFormFactor: 'DESKTOP',
    mpName: 'voyager-web', displayDensity: 1, displayWidth: 1280, displayHeight: 720,
  }),
};



const ts = () => new Date().toISOString().substring(11, 19);
const encodeUrn = (urn) => urn.replace(/:/g, '%3A').replace(/\(/g, '%28').replace(/\)/g, '%29').replace(/,/g, '%2C').replace(/=/g, '%3D');

let rateLimitCount = 0; // kept for the final summary (now: hits that triggered backoff)















async function apiFetch(guard, url) {
  for (let attempt = 0; attempt < safety.BACKOFF_MAX_ATTEMPTS + 1; attempt++) {

    guard.assertUnderCaps();


    await guard.randomDelay();

    let res = null;
    let bodyText = '';
    try {
      res = await fetch(url, { headers, redirect: 'manual' });

      guard.recordCall();
      try {
        bodyText = await res.text();
      } catch (e) {
        bodyText = '';
      }
    } catch (e) {

      const verdict = guard.classifyResponse(null, '');

      void verdict;
      rateLimitCount++;
      await guard.expBackoffTransient();
      continue;
    }



    const verdict = guard.classifyResponse(res, bodyText);

    if (verdict === safety.OK) {
      guard.resetTransientBackoff();
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
      rateLimitCount++;
      console.log(`  [${ts()}] Transient error on request, backing off (attempt ${attempt + 1})`);

      await guard.expBackoffTransient();
      continue;
    }


    return null;
  }

  return null;
}



async function fetchFullThread(guard, conversationUrn) {
  const allMessages = [];
  const seenKeys = new Set();
  let createdBefore = null;
  let page = 0;

  while (page < MAX_PAGES_PER_THREAD) {
    page++;
    const encoded = encodeUrn(conversationUrn);


    let url;
    if (createdBefore) {
      url = `${BASE}/voyagerMessagingGraphQL/graphql?queryId=messengerMessages.5846eeb71c981f11e0134cb6626cc314&variables=(conversationUrn:${encoded},count:40,createdBefore:${createdBefore})`;
    } else {
      url = `${BASE}/voyagerMessagingGraphQL/graphql?queryId=messengerMessages.5846eeb71c981f11e0134cb6626cc314&variables=(conversationUrn:${encoded},count:40)`;
    }

    const data = await apiFetch(guard, url);
    if (!data) break;

    const included = data.included || data.data?.included || [];
    const messages = included.filter(i =>
      i['$type'] === 'com.linkedin.messenger.Message' ||
      i['$type']?.includes('Message')
    );

    if (messages.length === 0) break;

    let newCount = 0;
    let oldestTs = Infinity;

    for (const msg of messages) {
      const body = msg.body?.text || '';
      const deliveredAt = msg.deliveredAt;
      const key = `${deliveredAt}|${body.substring(0, 80)}`;

      if (!seenKeys.has(key)) {
        seenKeys.add(key);
        allMessages.push({
          senderIsMe: (msg['*sender'] || '').includes(MY_URN),
          body,
          deliveredAt: deliveredAt ? new Date(deliveredAt).toISOString() : null,
          subject: msg.subject || null,
        });
        newCount++;
      }

      if (deliveredAt && deliveredAt < oldestTs) {
        oldestTs = deliveredAt;
      }
    }


    if (newCount === 0) break;


    if (oldestTs < Infinity) {
      createdBefore = oldestTs;
    } else {
      break;
    }

    if (allMessages.length >= MAX_MESSAGES_PER_THREAD) break;


  }


  allMessages.sort((a, b) => (a.deliveredAt || '').localeCompare(b.deliveredAt || ''));
  return allMessages;
}



function loadCheckpoint() {
  if (fs.existsSync(CHECKPOINT_FILE)) {
    return JSON.parse(fs.readFileSync(CHECKPOINT_FILE, 'utf8'));
  }
  return { completed: {}, stats: { fetched: 0, totalMessages: 0 } };
}

function saveCheckpoint(checkpoint) {
  fs.writeFileSync(CHECKPOINT_FILE, JSON.stringify(checkpoint));
}



function parseSessionCap() {
  const idx = process.argv.indexOf('--session-cap');
  if (idx === -1 || idx + 1 >= process.argv.length) return undefined;
  const n = parseInt(process.argv[idx + 1], 10);
  if (Number.isNaN(n) || n <= 0) {
    console.error('--session-cap requires a positive integer');
    process.exit(1);
  }
  return n; // may only LOWER the cap; the guard throws if it exceeds policy.
}



async function main() {
  const resume = process.argv.includes('--resume');

  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║  SBK — LinkedIn Thread Expander                      ║');
  console.log('║  Fetch complete message threads for all conversations   ║');
  console.log('╚══════════════════════════════════════════════════════════╝\n');



  let guard;
  try {
    guard = new LinkedInSafetyGuard({ sessionCap: parseSessionCap() });
  } catch (e) {
    console.error(`[safety] ${e.message}`);
    process.exit(1);
  }
  console.log(`  Safety: session cap ${guard.sessionCap}, daily cap ${guard.dailyCap}, ` +
    `delay ${safety.MIN_DELAY_MS / 1000}-${safety.MAX_DELAY_MS / 1000}s jittered, serialized (no parallelism).\n`);


  const me = await apiFetch(guard, `${BASE}/me`);
  if (!me) { console.error('Login failed! Session expired?'); process.exit(1); }
  const myProfile = (me.included || []).find(e => e['$type']?.includes('MiniProfile'));
  console.log(`  Logged in as: ${myProfile?.firstName} ${myProfile?.lastName}\n`);


  if (!fs.existsSync(INPUT_FILE)) {
    console.error(`Input not found: ${INPUT_FILE}`);
    console.error('Run scrape-all-conversations.js first.');
    process.exit(1);
  }

  const raw = JSON.parse(fs.readFileSync(INPUT_FILE, 'utf8'));
  const conversations = raw.conversations;
  console.log(`  Loaded ${conversations.length} conversations from previous fetch\n`);


  let checkpoint = resume ? loadCheckpoint() : { completed: {}, stats: { fetched: 0, totalMessages: 0 } };
  const skippedFromCheckpoint = Object.keys(checkpoint.completed).length;
  if (skippedFromCheckpoint > 0) {
    console.log(`  Resuming: ${skippedFromCheckpoint} conversations already done\n`);
  }


  const withSent = conversations.filter(c => c.hasMySentMessage);
  const withoutSent = conversations.filter(c => !c.hasMySentMessage);
  const allToProcess = [...withSent, ...withoutSent];

  console.log(`  Priority: ${withSent.length} with your sent messages`);
  console.log(`  Secondary: ${withoutSent.length} received-only\n`);
  console.log('  Fetching full threads (conservative pace; resume across days)...\n');

  let fetchedCount = skippedFromCheckpoint;
  let totalMessages = checkpoint.stats.totalMessages;
  let errors = 0;
  let stoppedOnCap = false;
  const startTime = Date.now();


  for (let i = 0; i < allToProcess.length; i++) {
    const conv = allToProcess[i];
    const urn = conv.entityUrn;
    if (!urn) continue;


    if (checkpoint.completed[urn]) {
      conv.messages = checkpoint.completed[urn];
      conv.totalMessages = conv.messages.length;
      conv.mySentCount = conv.messages.filter(m => m.senderIsMe).length;
      continue;
    }

    try {
      const messages = await fetchFullThread(guard, urn);
      conv.messages = messages;
      conv.totalMessages = messages.length;
      conv.mySentCount = messages.filter(m => m.senderIsMe).length;


      checkpoint.completed[urn] = messages;
      totalMessages += messages.length;
    } catch (e) {


      const msg = (e && e.message) || String(e);
      if (/cap reached/i.test(msg)) {
        console.log(`\n  [${ts()}] ${msg}`);
        console.log('  Stopping cleanly. Re-run with --resume to continue.\n');
        stoppedOnCap = true;
      } else {
        console.log(`\n  [${ts()}] Aborting: ${msg}`);
        stoppedOnCap = true;
      }

      checkpoint.stats = { fetched: fetchedCount, totalMessages };
      saveCheckpoint(checkpoint);
      break;
    }

    fetchedCount++;


    const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
    const phase = fetchedCount <= withSent.length ? 'PRIORITY' : 'SECONDARY';
    console.log(`  [${ts()}] [${phase}] ${fetchedCount}/${allToProcess.length} | ${totalMessages} msgs | ${errors} errors | ${elapsed}s elapsed | session ${guard.sessionCalls}/${guard.sessionCap}`);


    if (fetchedCount % 10 === 0) {
      checkpoint.stats = { fetched: fetchedCount, totalMessages };
      saveCheckpoint(checkpoint);
    }
  }


  checkpoint.stats = { fetched: fetchedCount, totalMessages };
  saveCheckpoint(checkpoint);


  console.log('\n  Building final output...\n');

  const totalSent = allToProcess.reduce((s, c) => s + (c.mySentCount || 0), 0);
  const totalReceived = totalMessages - totalSent;
  const withMsgs = allToProcess.filter(c => (c.totalMessages || 0) > 0).length;

  const output = {
    source: 'linkedin-standard-complete',
    fetchedAt: new Date().toISOString(),
    basedOn: raw.fetchedAt,
    partial: stoppedOnCap, // true if we stopped on a cap / abort (resume later)
    stats: {
      totalConversations: allToProcess.length,
      conversationsWithMessages: withMsgs,
      totalMessages,
      sentByYou: totalSent,
      received: totalReceived,
      errors,
    },
    conversations: allToProcess.map(c => ({
      entityUrn: c.entityUrn,
      backendUrn: c.backendUrn,
      createdAt: c.createdAt,
      lastActivityAt: c.lastActivityAt,
      categories: c.categories,
      participants: c.participants,
      totalMessages: c.totalMessages || 0,
      mySentCount: c.mySentCount || 0,
      messages: c.messages || [],
    })),
  };

  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
  console.log(`  Saved → ${OUTPUT_FILE}`);
  console.log(`  Size: ${(fs.statSync(OUTPUT_FILE).size / 1024 / 1024).toFixed(1)} MB\n`);


  if (!stoppedOnCap && fs.existsSync(CHECKPOINT_FILE)) fs.unlinkSync(CHECKPOINT_FILE);


  console.log('═'.repeat(60));
  console.log(stoppedOnCap ? '  STOPPED (partial — resume with --resume)' : '  COMPLETED');
  console.log('═'.repeat(60));
  console.log(`  Conversations: ${allToProcess.length}`);
  console.log(`  With messages: ${withMsgs}`);
  console.log(`  Total messages: ${totalMessages}`);
  console.log(`  Sent by you: ${totalSent}`);
  console.log(`  Received: ${totalReceived}`);
  console.log(`  Errors: ${errors}`);
  console.log(`  Backoff/transient hits: ${rateLimitCount}`);
  console.log(`  Session calls: ${guard.sessionCalls}/${guard.sessionCap}`);
  console.log(`  Time: ${((Date.now() - startTime) / 1000 / 60).toFixed(1)} minutes`);
  console.log('═'.repeat(60) + '\n');
}

main().catch(e => {
  console.error('\nFATAL:', e.message);
  process.exit(1);
});
