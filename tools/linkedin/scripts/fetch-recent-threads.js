#!/usr/bin/env node















const fs = require('fs');
const path = require('path');



const safety = require('./li-safety.js');
const { LinkedInSafetyGuard, OK, GONE, TRANSIENT } = safety;


// Under the data root (SBK_DATA_ROOT, default ~/.sbk-data), never in the repo.
const SESSION_FILE = process.env.LINKEDIN_SESSION
  || path.join(process.env.SBK_DATA_ROOT || path.join(require('os').homedir(), '.sbk-data'), 'linkedin', 'raw', 'linkedin-session.json');

const ownUrn = require('./li-own-urn.js');
// Your own member id: SBK_LINKEDIN_OWN_URN or sbk.config.json linkedin.own_urn, else read from LinkedIn below.
let MY_URN = ownUrn.ownUrnFromConfig();
const VOYAGER_BASE = 'https://www.linkedin.com/voyager/api';



const MAX_MESSAGES_PER_THREAD = 200;
const MAX_CONV_PAGES = 5;       // per inbox category (was 100)
const MAX_THREAD_PAGES = 5;     // per conversation full-thread fetch (was 20)


const args = process.argv.slice(2);
const sinceIdx = args.indexOf('--since');
const sinceDate = sinceIdx >= 0 ? args[sinceIdx + 1] : '2020-01-01';
const sinceDateMs = new Date(sinceDate + 'T00:00:00Z').getTime();

const outputIdx = args.indexOf('--output');
const OUTPUT_DIR = path.join(process.env.SBK_DATA_ROOT || path.join(require('os').homedir(), '.sbk-data'), 'linkedin', 'raw');
const OUTPUT_FILE = outputIdx >= 0 ? args[outputIdx + 1]
  : path.join(OUTPUT_DIR, 'linkedin-threads-recent.json');


function loadSession() {
  if (!fs.existsSync(SESSION_FILE)) {
    console.error('Session file not found: ' + SESSION_FILE);
    process.exit(1);
  }
  const session = JSON.parse(fs.readFileSync(SESSION_FILE, 'utf8'));
  const li_at = session.cookies.find(c => c.name === 'li_at');
  const jsessionid = session.cookies.find(c => c.name === 'JSESSIONID');
  if (!li_at || !jsessionid) {
    console.error('Session missing li_at or JSESSIONID.');
    process.exit(1);
  }
  return {
    li_at: li_at.value,
    jsessionid: jsessionid.value,
    csrf: jsessionid.value.replace(/"/g, ''),
  };
}

function makeHeaders(session, accept) {
  return {
    'csrf-token': session.csrf,
    'cookie': 'li_at=' + session.li_at + '; JSESSIONID=' + session.jsessionid,
    'x-restli-protocol-version': '2.0.0',
    'x-li-lang': 'en_US',
    'accept': accept || 'application/vnd.linkedin.normalized+json+2.1',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'x-li-track': JSON.stringify({
      clientVersion: '1.13.42316', mpVersion: '1.13.42316', osName: 'web',
      timezoneOffset: 0, timezone: 'UTC', deviceFormFactor: 'DESKTOP',
      mpName: 'voyager-web', displayDensity: 1, displayWidth: 1280, displayHeight: 720,
    }),
  };
}

const encodeUrn = (urn) => urn.replace(/:/g, '%3A').replace(/\(/g, '%28').replace(/\)/g, '%29').replace(/,/g, '%2C').replace(/=/g, '%3D');
const ts = () => new Date().toISOString().substring(11, 19);




const guard = new LinkedInSafetyGuard();















async function apiFetch(url, headers) {
  for (;;) {

    guard.assertUnderCaps();

    let res = null;
    let bodyText = '';
    try {
      res = await fetch(url, { headers });
      guard.recordCall(); // effective call toward LinkedIn -> counts to daily budget
      bodyText = await res.text();
    } catch (e) {

      const verdict = guard.classifyResponse(null, '');
      if (verdict === TRANSIENT) {
        console.log('  Network error, backing off: ' + (e && e.message));
        await guard.expBackoffTransient(); // throws after 3 attempts -> abort run
        continue;
      }
      return null;
    }


    const verdict = guard.classifyResponse(res, bodyText);

    if (verdict === OK) {
      guard.resetTransientBackoff();
      try {
        return JSON.parse(bodyText);
      } catch (e) {
        console.log('  Unparseable JSON body, skipping item.');
        return null;
      }
    }

    if (verdict === GONE) {
      console.log('  HTTP ' + res.status + ' (missing/bad resource), skipping.');
      return null;
    }

    if (verdict === TRANSIENT) {
      console.log('  Transient (HTTP ' + res.status + '), backing off.');
      await guard.expBackoffTransient(); // throws after 3 attempts -> abort run
      continue;
    }


    return null;
  }
}


async function fetchConvPage(category, cursor, headers) {
  const mailbox = 'urn%3Ali%3Afsd_profile%3A' + MY_URN;
  let params;
  if (cursor) {
    params = '(query:(predicateUnions:List((conversationCategoryPredicate:(category:' + category + ')))),count:20,mailboxUrn:' + mailbox + ',cursor:' + cursor + ')';
  } else {
    params = '(query:(predicateUnions:List((conversationCategoryPredicate:(category:' + category + ')))),count:20,mailboxUrn:' + mailbox + ')';
  }
  return apiFetch(
    VOYAGER_BASE + '/voyagerMessagingGraphQL/graphql?queryId=messengerConversations.9501074288a12f3ae9e3c7ea243bccbf&variables=' + params,
    headers
  );
}

function parseConv(conv) {
  const participants = (conv.conversationParticipants || []).map(p => {
    const member = p && p.participantType && p.participantType.member;
    if (member) {
      const firstName = (member.firstName && member.firstName.text) || '';
      const lastName = (member.lastName && member.lastName.text) || '';
      return {
        name: (firstName + ' ' + lastName).trim(),
        profileUrl: member.profileUrl || '',
        urn: p.hostIdentityUrn || '',
      };
    }
    return { name: 'Unknown', urn: (p && p.hostIdentityUrn) || '' };
  }).filter(p => p.urn.indexOf(MY_URN) === -1);

  const inlineMessages = ((conv.messages && conv.messages.elements) || []).map(msg => ({
    senderIsMe: ((msg.sender && msg.sender.hostIdentityUrn) || '').indexOf(MY_URN) >= 0,
    body: (msg.body && msg.body.text) || '',
    deliveredAt: msg.deliveredAt ? new Date(msg.deliveredAt).toISOString() : null,
    subject: msg.subject || null,
  }));

  return {
    entityUrn: conv.entityUrn || conv.backendUrn || '',
    backendUrn: conv.backendUrn || '',
    createdAt: conv.createdAt ? new Date(conv.createdAt).toISOString() : null,
    lastActivityAt: conv.lastActivityAt ? new Date(conv.lastActivityAt).toISOString() : null,
    categories: conv.categories || [],
    participants: participants,
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

  while (page < MAX_THREAD_PAGES) {
    page++;
    const encoded = encodeUrn(conversationUrn);
    let params;
    if (cursor) {
      params = '(conversationUrn:' + encoded + ',count:40,cursor:' + cursor + ')';
    } else {
      params = '(conversationUrn:' + encoded + ',count:40)';
    }

    const data = await apiFetch(
      VOYAGER_BASE + '/voyagerMessagingGraphQL/graphql?queryId=messengerMessages.5846eeb71c981f11e0134cb6626cc314&variables=' + params,
      headers
    );

    if (!data) break;

    const included = data.included || (data.data && data.data.included) || [];
    const messages = included.filter(i => i['$type'] === 'com.linkedin.messenger.Message');

    for (const msg of messages) {
      const key = msg.deliveredAt + '|' + ((msg.body && msg.body.text) || '').substring(0, 50);
      if (!seenKeys.has(key)) {
        seenKeys.add(key);
        allMessages.push({
          senderIsMe: ((msg['*sender'] || '').indexOf(MY_URN) >= 0),
          body: (msg.body && msg.body.text) || '',
          deliveredAt: msg.deliveredAt ? new Date(msg.deliveredAt).toISOString() : null,
          subject: msg.subject || null,
        });
      }
    }


    const metadata = (data.data && data.data.messengerMessagesByCriteria && data.data.messengerMessagesByCriteria.metadata)
      || (data.data && data.data.messengerMessages && data.data.messengerMessages.metadata) || {};
    cursor = metadata.previousCursor || metadata.nextCursor || null;

    if (!cursor || messages.length === 0 || allMessages.length >= MAX_MESSAGES_PER_THREAD) break;
    await guard.randomDelay(); // 45-120s jittered floor between LinkedIn calls
  }

  allMessages.sort((a, b) => (a.deliveredAt || '').localeCompare(b.deliveredAt || ''));
  return allMessages;
}

async function main() {
  console.log('SBK -- LinkedIn Recent Threads Fetcher');
  console.log('Since: ' + sinceDate + ' (' + new Date(sinceDateMs).toISOString() + ')');
  console.log('Output: ' + OUTPUT_FILE);
  console.log('Safety: shared guard active (session cap ' + guard.sessionCap
    + ', daily cap ' + guard.dailyCap + ', delay 45-120s, kill-switch armed)');
  console.log('');

  const session = loadSession();
  const graphqlHeaders = makeHeaders(session, 'application/graphql');
  const normalizedHeaders = makeHeaders(session);


  const me = await apiFetch(VOYAGER_BASE + '/me', normalizedHeaders);
  if (!me) { console.error('Login failed.'); process.exit(1); }
  const myProfile = (me.included || []).find(e => (e['$type'] || '').indexOf('MiniProfile') >= 0);
  console.log('Logged in as: ' + (myProfile ? myProfile.firstName + ' ' + myProfile.lastName : 'unknown'));
  MY_URN = ownUrn.requireOwnUrn(MY_URN || ownUrn.ownUrnFromMe(me));
  console.log('');


  const allConvos = [];
  const seenUrns = new Set();

  for (const category of ['PRIMARY_INBOX', 'SECONDARY_INBOX']) {
    console.log('Fetching ' + category + '...');
    let cursor = null;
    let page = 0;
    let reachedCutoff = false;

    while (page < MAX_CONV_PAGES && !reachedCutoff) {
      page++;
      const data = await fetchConvPage(category, cursor, graphqlHeaders);
      if (!data) break;

      const result = (data.data && data.data.messengerConversationsByCategoryQuery)
        || (data.data && data.data.messengerConversationsBySyncToken) || {};
      const elements = result.elements || [];

      if (elements.length === 0) break;

      let newCount = 0;
      for (const conv of elements) {
        const urn = conv.entityUrn || conv.backendUrn;
        if (!urn || seenUrns.has(urn)) continue;


        const lastActivity = conv.lastActivityAt || 0;
        if (lastActivity < sinceDateMs) {
          reachedCutoff = true;
          break;
        }

        seenUrns.add(urn);
        allConvos.push(parseConv(conv));
        newCount++;
      }

      console.log('  Page ' + page + ': +' + newCount + ' new conversations (total: ' + allConvos.length + ')');

      cursor = (result.metadata && result.metadata.nextCursor) || null;
      if (!cursor) break;
      await guard.randomDelay(); // 45-120s jittered floor between LinkedIn calls
    }

    if (reachedCutoff) {
      console.log('  Reached cutoff date, stopping ' + category);
    }
    console.log('');
  }

  console.log('Total recent conversations: ' + allConvos.length);
  console.log('');

  if (allConvos.length === 0) {
    console.log('No new conversations found since ' + sinceDate);
    return;
  }


  console.log('Fetching full message threads...');
  let fetched = 0;
  let totalMessages = 0;

  for (const conv of allConvos) {
    if (conv.messages.length <= 2 && conv.entityUrn) {
      const messages = await fetchFullThread(conv.entityUrn, normalizedHeaders);
      if (messages.length > 0) {
        conv.messages = messages;
        conv.totalMessages = messages.length;
        conv.mySentCount = messages.filter(m => m.senderIsMe).length;
      }
    }
    fetched++;
    totalMessages += conv.messages.length;

    if (fetched % 10 === 0 || fetched === allConvos.length) {
      console.log('  [' + ts() + '] ' + fetched + '/' + allConvos.length + ' threads | ' + totalMessages + ' messages');
    }
    await guard.randomDelay(); // 45-120s jittered floor between LinkedIn calls
  }


  const outputDir = path.dirname(OUTPUT_FILE);
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  const totalSent = allConvos.reduce((s, c) => s + (c.messages || []).filter(m => m.senderIsMe).length, 0);
  const totalMsgs = allConvos.reduce((s, c) => s + (c.messages || []).length, 0);

  const output = {
    source: 'linkedin-standard-incremental',
    fetchedAt: new Date().toISOString(),
    sinceCutoff: sinceDate,
    stats: {
      totalConversations: allConvos.length,
      totalMessages: totalMsgs,
      sentByYou: totalSent,
      received: totalMsgs - totalSent,
      sessionCalls: guard.sessionCalls,
    },
    conversations: allConvos,
  };

  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
  console.log('');
  console.log('Saved to: ' + OUTPUT_FILE);
  console.log('Size: ' + (fs.statSync(OUTPUT_FILE).size / 1024).toFixed(1) + ' KB');
  console.log('');
  console.log('SUMMARY');
  console.log('  Conversations: ' + allConvos.length);
  console.log('  Messages: ' + totalMsgs + ' (sent: ' + totalSent + ', received: ' + (totalMsgs - totalSent) + ')');
  console.log('  LinkedIn calls this run: ' + guard.sessionCalls);


  console.log('');
  console.log('Recent conversations:');
  const sorted = allConvos.sort((a, b) => (b.lastActivityAt || '').localeCompare(a.lastActivityAt || ''));
  for (const conv of sorted.slice(0, 15)) {
    const names = conv.participants.map(p => p.name).join(', ') || 'Unknown';
    const msgs = conv.messages.length;
    const last = conv.lastActivityAt ? conv.lastActivityAt.substring(0, 16) : 'n/a';
    console.log('  ' + names + ' | ' + msgs + ' msgs | last: ' + last);
  }
}

main().catch(e => {
  console.error('FATAL:', e.message);
  process.exit(1);
});
