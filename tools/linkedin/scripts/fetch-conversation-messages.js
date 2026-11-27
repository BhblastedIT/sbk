const fs = require('fs');
// Files go under the data root (SBK_DATA_ROOT, default ~/.sbk-data), never in the repo or the current folder.
const LI_RAW = require('path').join(process.env.SBK_DATA_ROOT || require('path').join(require('os').homedir(), '.sbk-data'), 'linkedin', 'raw');
fs.mkdirSync(LI_RAW, { recursive: true });
const {
  LinkedInSafetyGuard,
  OK,
  GONE,
  TRANSIENT,
} = require('./li-safety.js');















const session = JSON.parse(fs.readFileSync('./linkedin-session.json', 'utf8'));
const li_at = session.cookies.find(c => c.name === 'li_at').value;
const jsessionid = session.cookies.find(c => c.name === 'JSESSIONID').value;
const csrf = jsessionid.replace(/"/g, '');

const ownUrn = require('./li-own-urn.js');
// Your own member id: SBK_LINKEDIN_OWN_URN or sbk.config.json linkedin.own_urn, else the one saved by scrape-all-conversations.js.
let MY_URN = ownUrn.ownUrnFromConfig();
const BASE = 'https://www.linkedin.com/voyager/api';
const INPUT_FILE = require('path').join(LI_RAW, 'linkedin-all-conversations-raw.json');

const headers = {
  'csrf-token': csrf,
  'cookie': `li_at=${li_at}; JSESSIONID=${jsessionid}`,
  'x-restli-protocol-version': '2.0.0',
  'x-li-lang': 'en_US',
  'accept': 'application/vnd.linkedin.normalized+json+2.1',
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
  'x-li-track': JSON.stringify({
    clientVersion: '1.13.42316', mpVersion: '1.13.42316', osName: 'web',
    timezoneOffset: 0, timezone: 'UTC', deviceFormFactor: 'DESKTOP',
    mpName: 'voyager-web', displayDensity: 1, displayWidth: 1280, displayHeight: 720,
  }),
};

function encodeRestliUrn(urn) {
  return urn.replace(/:/g, '%3A').replace(/\(/g, '%28').replace(/\)/g, '%29').replace(/,/g, '%2C').replace(/=/g, '%3D');
}





async function fetchMessagesSafe(guard, conversationUrn) {
  const encoded = encodeRestliUrn(conversationUrn);
  const url = `${BASE}/voyagerMessagingGraphQL/graphql?queryId=messengerMessages.5846eeb71c981f11e0134cb6626cc314&variables=(conversationUrn:${encoded})`;


  while (true) {
    guard.assertUnderCaps(); // throws when session/daily cap reached -> stop run

    let res = null;
    let bodyText = '';
    try {
      res = await fetch(url, { headers, redirect: 'manual' });
      bodyText = await res.text();
    } catch (e) {

      res = null;
      bodyText = '';
    } finally {

      guard.recordCall();
    }



    const verdict = guard.classifyResponse(
      res ? { status: res.status, url: (res && res.url) || url } : null,
      bodyText
    );

    if (verdict === OK) {
      guard.resetTransientBackoff();
      let data;
      try {
        data = JSON.parse(bodyText);
      } catch (e) {
        return { messages: [] };
      }
      const included = data.included || data.data?.included || [];
      return {
        messages: included.filter(i => i['$type'] === 'com.linkedin.messenger.Message'),
      };
    }

    if (verdict === GONE) {

      guard.resetTransientBackoff();
      return { messages: [] };
    }

    if (verdict === TRANSIENT) {

      await guard.expBackoffTransient();
      continue;
    }


    return { messages: [] };
  }
}

function extractSentNotes(conv, parsedMessages) {
  const notes = [];
  for (const msg of parsedMessages.filter(m => m.senderIsMe && m.body)) {
    notes.push({
      to: conv.participants.map(p => p.name).join(', '),
      toUrl: conv.participants.map(p => p.profileUrl).join(', '),
      date: msg.deliveredAt,
      subject: msg.subject,
      body: msg.body,
      conversationCreatedAt: conv.createdAt,
      categories: conv.categories,
      isConnectionNote: conv.createdAt && msg.deliveredAt &&
        conv.createdAt.substring(0, 16) === msg.deliveredAt.substring(0, 16),
    });
  }
  return notes;
}

function buildMessages(conv, fetched) {
  if (fetched.messages.length > 0) {
    const msgSeen = new Set();
    return fetched.messages
      .map(msg => {
        const key = `${msg.deliveredAt}|${(msg.body?.text || '').substring(0, 50)}`;
        if (msgSeen.has(key)) return null;
        msgSeen.add(key);
        return {
          senderIsMe: (msg['*sender'] || '').includes(MY_URN),
          body: msg.body?.text || '',
          deliveredAt: msg.deliveredAt ? new Date(msg.deliveredAt).toISOString() : null,
          subject: msg.subject || null,
        };
      })
      .filter(Boolean);
  }
  return conv.inlineMessages || [];
}

async function main() {
  console.log('=== Phase 2: Fetch messages via direct API (SAFE / serial) ===\n');



  const guard = new LinkedInSafetyGuard();

  if (!fs.existsSync(INPUT_FILE)) {
    console.log(`ERROR: ${INPUT_FILE} not found. Run scrape-all-conversations.js first.`);
    return;
  }

  const raw = JSON.parse(fs.readFileSync(INPUT_FILE, 'utf8'));
  MY_URN = ownUrn.requireOwnUrn(MY_URN || ownUrn.idFromUrn(raw.myUrn));
  const conversations = raw.conversations;
  console.log(`Loaded ${conversations.length} conversations\n`);
  console.log(
    `Caps: session ${guard.sessionCap} calls/run, daily ${guard.dailyCap} calls/day ` +
      `(used today: ${guard.loadDailyCap()}). Delay: jittered 45-120s. Serial only.\n`
  );


  const withSent = conversations.filter(c => c.hasMySentMessage);
  const withoutSent = conversations.filter(c => !c.hasMySentMessage);
  console.log(`  Priority: ${withSent.length} conversations with known sent messages`);
  console.log(`  Secondary: ${withoutSent.length} conversations to check\n`);

  const myNotes = [];
  let fetchedCount = 0;
  let withMessages = 0;


  const allToProcess = [...withSent, ...withoutSent];

  for (let i = 0; i < allToProcess.length; i++) {
    const conv = allToProcess[i];


    try {
      guard.assertUnderCaps();
    } catch (e) {
      console.log(`\n[STOP] ${e.message}`);
      console.log(`  Processed ${fetchedCount}/${allToProcess.length} conversations this run.`);
      break;
    }

    const fetched = await fetchMessagesSafe(guard, conv.entityUrn);
    fetchedCount++;

    conv.messages = buildMessages(conv, fetched);
    if (fetched.messages.length > 0) withMessages++;

    conv.totalMessages = conv.messages.length;
    conv.mySentCount = conv.messages.filter(m => m.senderIsMe).length;
    myNotes.push(...extractSentNotes(conv, conv.messages));

    if (fetchedCount % 10 === 0 || fetchedCount === withSent.length) {
      const phase = fetchedCount <= withSent.length ? 'PRIORITY' : 'SECONDARY';
      console.log(`  [${phase}] ${fetchedCount}/${allToProcess.length} | ${withMessages} with msgs | ${myNotes.length} sent notes | daily ${guard.loadDailyCap()}/${guard.dailyCap}`);
    }


    const interimNotes = [...myNotes].sort((a, b) => (b.date || '').localeCompare(a.date || ''));
    fs.writeFileSync(require('path').join(LI_RAW, 'linkedin-sent-notes.json'), JSON.stringify(interimNotes, null, 2));


    if (i < allToProcess.length - 1) {
      await guard.randomDelay();
    }
  }

  myNotes.sort((a, b) => (b.date || '').localeCompare(a.date || ''));


  console.log('\nSaving final output...\n');

  const output = {
    fetchedAt: new Date().toISOString(),
    stats: {
      totalConversations: conversations.length,
      conversationsWithMessages: withMessages,
      totalSentMessages: myNotes.length,
      connectionNotes: myNotes.filter(n => n.isConnectionNote).length,
      uniqueRecipients: new Set(myNotes.map(n => n.to)).size,
    },
    sentMessages: myNotes,
    conversations: conversations.map(c => ({
      entityUrn: c.entityUrn,
      participants: c.participants,
      createdAt: c.createdAt,
      lastActivityAt: c.lastActivityAt,
      categories: c.categories,
      totalMessages: c.totalMessages || 0,
      mySentCount: c.mySentCount || 0,
      messages: c.messages || [],
    })),
  };

  fs.writeFileSync(require('path').join(LI_RAW, 'linkedin-all-messages.json'), JSON.stringify(output, null, 2));
  console.log('  Saved to ' + require('path').join(LI_RAW, 'linkedin-all-messages.json'));

  fs.writeFileSync(require('path').join(LI_RAW, 'linkedin-sent-notes.json'), JSON.stringify(myNotes, null, 2));
  console.log(`  Saved ${myNotes.length} sent messages to ${LI_RAW}/linkedin-sent-notes.json`);


  console.log('\n=== FINAL SUMMARY ===');
  console.log(`  Total conversations: ${conversations.length}`);
  console.log(`  With messages fetched: ${withMessages}`);
  console.log(`  Your sent messages: ${myNotes.length}`);
  console.log(`  Connection notes: ${myNotes.filter(n => n.isConnectionNote).length}`);
  console.log(`  Unique recipients: ${new Set(myNotes.map(n => n.to)).size}`);

  if (myNotes.length > 0) {
    console.log('\n  --- Recent sent messages (top 15): ---\n');
    for (const note of myNotes.slice(0, 15)) {
      const tag = note.isConnectionNote ? ' [CONNECTION NOTE]' : '';
      console.log(`  To: ${note.to}${tag}`);
      console.log(`  Date: ${note.date}`);
      console.log(`  Body: ${note.body.substring(0, 150)}${note.body.length > 150 ? '...' : ''}`);
      console.log('  ---');
    }
  }
}

main().catch(e => { console.error(e); process.exitCode = 1; });
