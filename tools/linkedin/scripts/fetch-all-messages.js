const fs = require('fs');
const safety = require('./li-safety.js');
const { LinkedInSafetyGuard } = safety;






const guard = new LinkedInSafetyGuard();

const session = JSON.parse(fs.readFileSync('./linkedin-session.json', 'utf8'));
const li_at = session.cookies.find(c => c.name === 'li_at').value;
const jsessionid = session.cookies.find(c => c.name === 'JSESSIONID').value;
const csrf = jsessionid.replace(/"/g, '');

const MY_URN = 'ACoAAEXAMPLE_URN_PLACEHOLDER';
const BASE = 'https://www.linkedin.com/voyager/api';


const graphqlHeaders = {
  'csrf-token': csrf,
  'cookie': `li_at=${li_at}; JSESSIONID=${jsessionid}`,
  'x-restli-protocol-version': '2.0.0',
  'x-li-lang': 'en_US',
  'accept': 'application/graphql',
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
  'x-li-track': JSON.stringify({
    clientVersion: '1.13.42316', mpVersion: '1.13.42316', osName: 'web',
    timezoneOffset: 0, timezone: 'UTC', deviceFormFactor: 'DESKTOP',
    mpName: 'voyager-web', displayDensity: 1, displayWidth: 1280, displayHeight: 720,
  }),
};


const normalizedHeaders = {
  ...graphqlHeaders,
  'accept': 'application/vnd.linkedin.normalized+json+2.1',
};

function encodeRestliUrn(urn) {
  return urn.replace(/:/g, '%3A').replace(/\(/g, '%28').replace(/\)/g, '%29').replace(/,/g, '%2C').replace(/=/g, '%3D');
}
















async function guardedFetchJson(url, headers) {
  const fullUrl = url.startsWith('http') ? url : `${BASE}${url}`;



  guard.assertUnderCaps();


  guard.checkKillswitch();

  for (;;) {
    let res = null;
    let bodyText = '';
    try {
      res = await fetch(fullUrl, { headers, redirect: 'manual' });
      bodyText = await res.text();
    } catch (e) {

      res = null;
      bodyText = '';
    }


    guard.recordCall();



    const verdict = guard.classifyResponse(
      res ? { status: res.status, url: (res.url || fullUrl) } : null,
      bodyText
    );

    if (verdict === safety.OK) {
      guard.resetTransientBackoff();
      try {
        return JSON.parse(bodyText);
      } catch (e) {

        return null;
      }
    }

    if (verdict === safety.GONE) {
      guard.resetTransientBackoff();
      return null; // 404/400: skip this item, caller continues
    }

    if (verdict === safety.TRANSIENT) {

      await guard.expBackoffTransient();

      guard.assertUnderCaps();
      guard.checkKillswitch();
      continue;
    }


    return null;
  }
}

async function fetchGraphQL(url) {
  return guardedFetchJson(url, graphqlHeaders);
}

async function fetchNormalized(url) {
  return guardedFetchJson(url, normalizedHeaders);
}


function parseConversation(conv) {
  return {
    entityUrn: conv.entityUrn || conv.backendUrn,
    backendUrn: conv.backendUrn,
    createdAt: conv.createdAt,
    lastActivityAt: conv.lastActivityAt,
    categories: conv.categories || [],
    participants: (conv.conversationParticipants || []).map(p => {
      const member = p?.participantType?.member;
      if (member) {
        return {
          name: `${member.firstName?.text || ''} ${member.lastName?.text || ''}`.trim(),
          profileUrl: member.profileUrl || '',
          urn: p.hostIdentityUrn || '',
        };
      }
      return { name: 'Unknown', urn: p?.hostIdentityUrn || '' };
    }).filter(p => !p.urn.includes(MY_URN)),
    messages: (conv.messages?.elements || []).map(msg => ({
      senderIsMe: (msg.sender?.hostIdentityUrn || '').includes(MY_URN),
      body: msg.body?.text || '',
      deliveredAt: msg.deliveredAt ? new Date(msg.deliveredAt).toISOString() : null,
      subject: msg.subject || null,
    })),
  };
}

async function fetchConversationsPage(category, cursor) {
  const mailboxEncoded = `urn%3Ali%3Afsd_profile%3A${MY_URN}`;
  let params;
  if (cursor) {
    params = `(query:(predicateUnions:List((conversationCategoryPredicate:(category:${category})))),count:20,mailboxUrn:${mailboxEncoded},cursor:${cursor})`;
  } else {
    params = `(query:(predicateUnions:List((conversationCategoryPredicate:(category:${category})))),count:20,mailboxUrn:${mailboxEncoded})`;
  }

  const data = await fetchGraphQL(`/voyagerMessagingGraphQL/graphql?queryId=messengerConversations.9501074288a12f3ae9e3c7ea243bccbf&variables=${params}`);
  if (!data) return { conversations: [], nextCursor: null };


  const result = data.data?.messengerConversationsByCategoryQuery || data.data?.messengerConversationsBySyncToken || {};
  const elements = result.elements || [];
  const nextCursor = result.metadata?.nextCursor || null;

  return { conversations: elements, nextCursor };
}

async function fetchAllConversationsForCategory(category) {
  const seenUrns = new Set();
  const allConvos = [];
  let cursor = null;
  let pageNum = 0;




  const MAX_PAGES = 25;

  for (;;) {
    pageNum++;
    const result = await fetchConversationsPage(category, cursor);

    let newCount = 0;
    for (const conv of result.conversations) {
      const urn = conv.entityUrn || conv.backendUrn;
      if (urn && !seenUrns.has(urn)) {
        seenUrns.add(urn);
        allConvos.push(conv);
        newCount++;
      }
    }

    console.log(`    [${category}] Page ${pageNum}: ${result.conversations.length} raw, ${newCount} new (total: ${allConvos.length}) | cursor: ${result.nextCursor ? 'yes' : 'no'}`);

    if (!result.nextCursor || result.conversations.length === 0) break;
    cursor = result.nextCursor;

    if (pageNum >= MAX_PAGES) { console.log('    Max pages reached (conservative ceiling)'); break; }


    await guard.randomDelay();
  }

  return allConvos;
}

async function fetchMessagesForConversation(conversationUrn) {
  const encoded = encodeRestliUrn(conversationUrn);

  const data = await fetchNormalized(
    `/voyagerMessagingGraphQL/graphql?queryId=messengerMessages.5846eeb71c981f11e0134cb6626cc314&variables=(conversationUrn:${encoded})`
  );
  if (!data) return [];
  const included = data.included || data.data?.included || [];
  return included.filter(i => i['$type'] === 'com.linkedin.messenger.Message');
}

async function main() {
  console.log('=== Fetch ALL LinkedIn Conversations & Messages (v3 - cursor pagination) ===\n');


  const me = await fetchNormalized('/me');
  if (!me) { console.log('Login failed!'); return; }
  const myProfile = (me.included || []).find(e => e['$type']?.includes('MiniProfile'));
  console.log(`Logged in as: ${myProfile?.firstName} ${myProfile?.lastName}\n`);


  console.log('--- Step 1: Fetching all conversations ---\n');

  console.log('  Fetching PRIMARY_INBOX...');
  const primaryConvos = await fetchAllConversationsForCategory('PRIMARY_INBOX');

  console.log('\n  Fetching SECONDARY_INBOX...');
  const secondaryConvos = await fetchAllConversationsForCategory('SECONDARY_INBOX');


  const seenUrns = new Set();
  const allConvos = [];
  for (const conv of [...primaryConvos, ...secondaryConvos]) {
    const urn = conv.entityUrn || conv.backendUrn;
    if (urn && !seenUrns.has(urn)) {
      seenUrns.add(urn);
      allConvos.push(conv);
    }
  }

  console.log(`\n  Total unique: ${allConvos.length} (primary: ${primaryConvos.length}, secondary: ${secondaryConvos.length})\n`);


  console.log('--- Step 2: Parsing conversation data ---\n');

  const parsed = allConvos.map(parseConversation);


  console.log('--- Step 3: Fetching full messages for conversations ---\n');

  let fetchCount = 0;
  for (const conv of parsed) {
    if (conv.messages.length <= 1 && conv.entityUrn) {
      fetchCount++;
      const messages = await fetchMessagesForConversation(conv.entityUrn);
      if (messages.length > 0) {
        const msgSeen = new Set();
        conv.messages = messages
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

      if (fetchCount % 20 === 0) {
        console.log(`  Fetched messages for ${fetchCount} conversations...`);
      }

      await guard.randomDelay();
    }
  }

  console.log(`  Fetched extra messages for ${fetchCount} conversations\n`);


  console.log('--- Step 4: Extracting sent messages ---\n');

  const myNotes = [];
  for (const conv of parsed) {
    for (const msg of conv.messages.filter(m => m.senderIsMe && m.body)) {
      myNotes.push({
        to: conv.participants.map(p => p.name).join(', '),
        toUrl: conv.participants.map(p => p.profileUrl).join(', '),
        date: msg.deliveredAt,
        subject: msg.subject,
        body: msg.body,
        conversationCreatedAt: conv.createdAt ? new Date(conv.createdAt).toISOString() : null,
        categories: conv.categories,
        isConnectionNote: conv.createdAt && msg.deliveredAt &&
          new Date(conv.createdAt).toISOString().substring(0, 16) === msg.deliveredAt.substring(0, 16),
      });
    }
  }

  myNotes.sort((a, b) => (b.date || '').localeCompare(a.date || ''));

  console.log(`  Total sent messages: ${myNotes.length}`);
  console.log(`  Connection notes: ${myNotes.filter(n => n.isConnectionNote).length}`);


  console.log('\n--- Step 5: Saving data ---\n');

  const output = {
    fetchedAt: new Date().toISOString(),
    profile: { firstName: myProfile?.firstName, lastName: myProfile?.lastName, urn: MY_URN },
    stats: {
      totalConversations: allConvos.length,
      primaryInbox: primaryConvos.length,
      secondaryInbox: secondaryConvos.length,
      conversationsWithMessages: parsed.filter(c => c.messages.length > 0).length,
      totalSentMessages: myNotes.length,
      connectionNotes: myNotes.filter(n => n.isConnectionNote).length,
    },
    sentMessages: myNotes,
    conversations: parsed.map(c => ({
      ...c,
      totalMessages: c.messages.length,
      mySentCount: c.messages.filter(m => m.senderIsMe).length,
    })),
  };

  fs.writeFileSync('./data/linkedin/linkedin-all-messages.json', JSON.stringify(output, null, 2));
  console.log('  Saved to data/linkedin/linkedin-all-messages.json');

  fs.writeFileSync('./data/linkedin/linkedin-sent-notes.json', JSON.stringify(myNotes, null, 2));
  console.log(`  Saved ${myNotes.length} sent messages to data/linkedin/linkedin-sent-notes.json`);


  console.log('\n=== FINAL SUMMARY ===');
  console.log(`  Total conversations: ${allConvos.length}`);
  console.log(`  PRIMARY_INBOX: ${primaryConvos.length}`);
  console.log(`  SECONDARY_INBOX: ${secondaryConvos.length}`);
  console.log(`  Messages sent by you: ${myNotes.length}`);
  console.log(`  Connection notes: ${myNotes.filter(n => n.isConnectionNote).length}`);

  if (myNotes.length > 0) {
    console.log('\n  --- Recent sent messages (top 10): ---\n');
    for (const note of myNotes.slice(0, 10)) {
      const tag = note.isConnectionNote ? ' [CONNECTION NOTE]' : '';
      console.log(`  To: ${note.to}${tag}`);
      console.log(`  Date: ${note.date}`);
      console.log(`  Body: ${note.body.substring(0, 120)}${note.body.length > 120 ? '...' : ''}`);
      console.log('  ---');
    }
  }
}

main().catch((err) => {



  console.error(`\n[fetch-all-messages] Run aborted: ${err && err.message ? err.message : err}`);
  console.error('  This is expected when the conservative LinkedIn caps are reached. Resume later/tomorrow.');
  process.exit(1);
});
