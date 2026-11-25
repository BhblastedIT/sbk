#!/usr/bin/env node



const fs = require('fs');

const COMPLETE_FILE = process.argv[2] || require('path').join(__dirname, '..', '..', '..', 'sbk', 'raw', 'linkedin', 'linkedin-threads-complete.json');
const RECENT_FILE = process.argv[3] || require('path').join(process.env.HOME, '.sbk-data', 'linkedin', 'raw', 'linkedin-threads-recent.json');

const complete = JSON.parse(fs.readFileSync(COMPLETE_FILE, 'utf8'));
const recent = JSON.parse(fs.readFileSync(RECENT_FILE, 'utf8'));

console.log('Existing conversations:', complete.conversations.length);
console.log('Recent conversations:', recent.conversations.length);


const convMap = new Map();
for (const conv of complete.conversations) {
  convMap.set(conv.entityUrn, conv);
}


let updated = 0, added = 0;
for (const conv of recent.conversations) {
  if (convMap.has(conv.entityUrn)) {
    const existing = convMap.get(conv.entityUrn);
    if (conv.messages && conv.messages.length > 0) {
      const existingDates = new Set(existing.messages.map(m => m.deliveredAt));
      let addedMsgs = 0;
      for (const msg of conv.messages) {
        if (msg.deliveredAt && !existingDates.has(msg.deliveredAt)) {
          existing.messages.push(msg);
          addedMsgs++;
        }
      }
      if (addedMsgs > 0) {
        existing.messages.sort((a, b) => (a.deliveredAt || '').localeCompare(b.deliveredAt || ''));
        existing.totalMessages = existing.messages.length;
        existing.mySentCount = existing.messages.filter(m => m.senderIsMe).length;
        existing.lastActivityAt = conv.lastActivityAt || existing.lastActivityAt;
        updated++;
        console.log('  Updated:', (conv.participants && conv.participants[0] && conv.participants[0].name) || '?', '+' + addedMsgs + ' msgs');
      }
    }
  } else {
    convMap.set(conv.entityUrn, conv);
    added++;
    console.log('  Added:', (conv.participants && conv.participants[0] && conv.participants[0].name) || '?', (conv.messages && conv.messages.length) || 0, 'msgs');
  }
}


const merged = Array.from(convMap.values());
merged.sort((a, b) => (b.lastActivityAt || '').localeCompare(a.lastActivityAt || ''));

const totalMsgs = merged.reduce((s, c) => s + (c.totalMessages || (c.messages && c.messages.length) || 0), 0);

const output = {
  source: 'linkedin-standard-complete',
  fetchedAt: new Date().toISOString(),
  basedOn: complete.basedOn || complete.fetchedAt,
  stats: { totalConversations: merged.length, totalMessages: totalMsgs },
  conversations: merged,
};

fs.writeFileSync(COMPLETE_FILE, JSON.stringify(output, null, 2));
console.log('\nResult:', merged.length, 'conversations,', totalMsgs, 'messages');
console.log('Updated:', updated, '| Added:', added);
console.log('Saved to:', COMPLETE_FILE);
console.log('Size:', (fs.statSync(COMPLETE_FILE).size / 1024 / 1024).toFixed(1), 'MB');
