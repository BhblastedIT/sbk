





















const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');


const safety = require('./li-safety.js');


const SESSION_CAP = 15;            // max profiles per run (below the global cap of 30)
const WORK_HOUR_START = 8;         // local working-hours window (inclusive)
const WORK_HOUR_END = 22;          // (exclusive)
const CONCURRENCY_LOCK = path.join(
  process.env.SBK_DATA_ROOT || path.join(os.homedir(), '.sbk-data'),
  'linkedin',
  '.linkedin-worker.lock'
);



const STOP_MARKERS = [
  'temporarily restricted',
  'software that automates activity',
  'unusual activity',
  '/authwall',
  '/checkpoint',
  '/challenge',
  'unusual traffic',          // Google bot-check
  'our systems have detected', // Google bot-check
];

function withinWorkWindow() {
  const h = new Date().getHours();
  return h >= WORK_HOUR_START && h < WORK_HOUR_END;
}

function acquireConcurrencyLock(workerId) {

  try {
    fs.mkdirSync(path.dirname(CONCURRENCY_LOCK), { recursive: true });
  } catch (e) {

  }
  if (fs.existsSync(CONCURRENCY_LOCK)) {
    let info = '';
    try {
      info = fs.readFileSync(CONCURRENCY_LOCK, 'utf8');
    } catch (e) {
      info = '(unreadable)';
    }
    process.stderr.write(
      '[linkedin-worker] Another worker is already running. ' +
        'Parallel access to LinkedIn is forbidden.\n' +
        `  lock: ${CONCURRENCY_LOCK}\n  holder: ${info}\n` +
        '  If this is a stale lock, remove it manually.\n'
    );
    process.exit(2);
  }
  fs.writeFileSync(
    CONCURRENCY_LOCK,
    JSON.stringify({ workerId, pid: process.pid, at: new Date().toISOString() })
  );
}

function releaseConcurrencyLock() {
  try {
    fs.unlinkSync(CONCURRENCY_LOCK);
  } catch (e) {

  }
}

// Minimal country -> aliases map (ISO 3166-1 alpha-2). This is a small sample;
// extend it from a full ISO country/city table or load it from user config.
const countryNames = {
  AU: ['Australia', 'Sydney', 'Melbourne'],
  BR: ['Brazil', 'Sao Paulo', 'Rio de Janeiro'],
  CA: ['Canada', 'Toronto', 'Vancouver'],
  DE: ['Germany', 'Berlin', 'Munich'],
  ES: ['Spain', 'Madrid', 'Barcelona'],
  FR: ['France', 'Paris'],
  GB: ['United Kingdom', 'UK', 'London'],
  IN: ['India', 'Mumbai', 'Delhi', 'Bangalore'],
  IT: ['Italy', 'Rome', 'Milan'],
  JP: ['Japan', 'Tokyo', 'Osaka'],
  NL: ['Netherlands', 'Amsterdam'],
  US: ['United States', 'USA', 'New York', 'San Francisco']
};

function normalizeStr(s) {
  return (s || '').toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();
}

function nameMatch(name1, name2) {
  const n1 = normalizeStr(name1).split(/\s+/);
  const n2 = normalizeStr(name2).split(/\s+/);
  let matched = 0;
  for (const p1 of n1) {
    for (const p2 of n2) {
      if (p1 === p2 && p1.length > 1) matched++;
      else if (p1.length > 2 && p2.length > 2 && (p1.startsWith(p2) || p2.startsWith(p1))) matched += 0.5;
    }
  }
  const minParts = Math.min(n1.length, n2.length);
  return matched >= Math.min(2, minParts) ? matched / Math.max(n1.length, n2.length) : 0;
}

function countryMatch(cc, loc) {
  if (!cc || !loc) return 0;
  const names = countryNames[cc] || [];
  for (const n of names) { if (loc.toLowerCase().includes(n.toLowerCase())) return 1; }
  return 0;
}

function textOverlap(t1, t2) {
  if (!t1 || !t2) return 0;
  const w1 = new Set(normalizeStr(t1).split(/\s+/).filter(w => w.length > 3));
  const w2 = new Set(normalizeStr(t2).split(/\s+/).filter(w => w.length > 3));
  let ov = 0;
  for (const w of w1) { if (w2.has(w)) ov++; }
  return w1.size > 0 ? ov / w1.size : 0;
}

function calcConfidence(inv, li) {
  let score = 0, max = 0;
  max += 40; score += nameMatch(inv.fullName, li.name) * 40;
  max += 20; score += countryMatch(inv.countryCode, li.location) * 20;
  if (inv.premiumDetails) {
    max += 25;
    score += textOverlap(inv.premiumDetails.businessName + ' ' + (inv.premiumDetails.jobRole || ''), li.headline + ' ' + (li.company || '')) * 25;
  } else if (inv.bio) {
    max += 25; score += textOverlap(inv.bio, li.headline) * 25;
  }
  if (inv.bio && li.headline) { max += 15; score += textOverlap(inv.bio, li.headline) * 15; }
  return max > 0 ? Math.round((score / max) * 100) : 0;
}

async function run() {
  const argv = process.argv.slice(2);
  const explicitRisk = argv.includes('--i-understand-the-risk');
  const positional = argv.filter((a) => !a.startsWith('--'));
  const startIdx = parseInt(positional[0]) || 0;
  const endIdx = parseInt(positional[1]) || 0;
  const workerId = positional[2] || '0';
  const outputFile = `linkedin-worker-${workerId}.json`;


  safety.checkKillswitch();


  if (!withinWorkWindow()) {
    console.error(
      `[linkedin-worker] Outside the working-hours window (${WORK_HOUR_START}:00-${WORK_HOUR_END}:00 local). Aborting.`
    );
    process.exit(2);
  }


  if (!explicitRisk) {
    console.error(
      '[linkedin-worker] BLOCKED. This worker performs mass automation that touches\n' +
        'LinkedIn (via Google) and can contribute to account restrictions.\n' +
        'Default = do not run. If you know what you are doing, run again with:\n' +
        `  node linkedin-worker.js ${startIdx} ${endIdx} ${workerId} --i-understand-the-risk\n` +
        'Conservative caps: ' +
        `${SESSION_CAP} profiles/run, shared daily budget ${safety.DEFAULT_DAILY_CAP}, delay 45-120s.\n`
    );
    process.exit(2);
  }


  acquireConcurrencyLock(workerId);
  process.on('exit', releaseConcurrencyLock);
  process.on('SIGINT', () => process.exit(130));
  process.on('SIGTERM', () => process.exit(143));


  const guard = new safety.LinkedInSafetyGuard({ sessionCap: SESSION_CAP });

  const db = JSON.parse(fs.readFileSync('contacts-api-database.json', 'utf-8'));
  const allTargets = db.contacts; // all profiles in the database
  const targets = allTargets.slice(startIdx, endIdx);

  console.log(
    `Worker ${workerId}: profiles ${startIdx}-${endIdx} (${targets.length} requested). ` +
      `Session cap ${SESSION_CAP}, shared daily budget ${safety.DEFAULT_DAILY_CAP}.`
  );

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
  });
  const page = await ctx.newPage();

  const results = [];

  for (let i = 0; i < targets.length; i++) {
    const inv = targets[i];
    const r = { id: inv.id, name: inv.fullName, linkedin: null, confidence: 0, source: null, snippet: '' };


    const liMatch = (inv.bio || '').match(/linkedin\.com\/in\/[\w\-]+/i);
    if (liMatch) {
      r.linkedin = 'https://www.' + liMatch[0];
      r.confidence = 95;
      r.source = 'bio';
      results.push(r);
      console.log(`W${workerId} [${i + 1}/${targets.length}] ${inv.fullName} ✅ bio (95%)`);
      continue;
    }


    try {
      guard.assertUnderCaps();
    } catch (capErr) {
      console.log(`W${workerId} STOP: ${capErr.message}`);
      break; // session/daily cap reached: clean shutdown
    }

    const company = inv.premiumDetails ? (inv.premiumDetails.businessName || '') : '';
    const companyClean = company.replace(/https?:\/\/[^\s]+/g, '').trim();
    const query = `"${inv.fullName}" ${companyClean} site:linkedin.com/in`.trim();

    try {
      const url = 'https://www.google.com/search?q=' + encodeURIComponent(query) + '&num=5';
      const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
      guard.recordCall(); // counts toward the shared budget (session + daily)



      const status = resp ? resp.status() : null;
      const finalUrl = page.url();
      let pageText = '';
      try {
        pageText = (await page.content()).toLowerCase();
      } catch (e) {

      }
      const hay = (finalUrl + ' ' + pageText).toLowerCase();
      if (status === 429 || status === 503) {

        fs.writeFileSync(outputFile, JSON.stringify(results, null, 2));
        safety.tripKillswitch(`Google/LinkedIn HTTP ${status} during search`);
      }
      for (const m of STOP_MARKERS) {
        if (hay.indexOf(m) !== -1) {
          fs.writeFileSync(outputFile, JSON.stringify(results, null, 2));
          safety.tripKillswitch(`Block/challenge marker detected: '${m}'`);
        }
      }

      const searchResults = await page.evaluate(() => {
        const items = [];
        document.querySelectorAll('a').forEach(a => {
          const href = a.href || '';
          if (href.includes('linkedin.com/in/')) {
            const match = href.match(/linkedin\.com\/in\/[\w\-]+/);
            if (match) {
              const parent = a.closest('div.g, div[data-sokoban-container]') || a.parentElement;
              const h3 = parent ? parent.querySelector('h3') : null;
              const snip = parent ? parent.querySelector('.VwiC3b, span.st, [data-sncf]') : null;
              items.push({
                url: 'https://www.' + match[0],
                title: h3 ? h3.innerText : a.innerText,
                snippet: snip ? snip.innerText : ''
              });
            }
          }
        });

        const seen = new Set();
        return items.filter(i => { if (seen.has(i.url)) return false; seen.add(i.url); return true; }).slice(0, 5);
      });

      let bestUrl = null, bestConf = 0, bestSnippet = '';

      for (const sr of searchResults) {
        const li = {
          name: sr.title.replace(/\s*[-–|].*$/, '').replace(/\s*LinkedIn$/i, '').trim(),
          headline: sr.title + ' ' + sr.snippet,
          location: sr.title + ' ' + sr.snippet,
          company: sr.snippet
        };
        const conf = calcConfidence(inv, li);
        if (conf > bestConf) {
          bestConf = conf;
          bestUrl = sr.url;
          bestSnippet = sr.snippet.substring(0, 150);
        }
      }

      if (bestUrl && bestConf >= 30) {
        r.linkedin = bestUrl;
        r.confidence = bestConf;
        r.source = 'google';
        r.snippet = bestSnippet;
        const icon = bestConf >= 70 ? '✅' : bestConf >= 50 ? '🟡' : '⚠️';
        console.log(`W${workerId} [${i + 1}/${targets.length}] ${inv.fullName} ${icon} ${bestUrl} (${bestConf}%)`);
      } else {
        console.log(`W${workerId} [${i + 1}/${targets.length}] ${inv.fullName} ❌`);
      }
    } catch (e) {
      console.log(`W${workerId} [${i + 1}/${targets.length}] ${inv.fullName} ERR: ${e.message.substring(0, 30)}`);
    }

    results.push(r);


    fs.writeFileSync(outputFile, JSON.stringify(results, null, 2));




    if (i < targets.length - 1) {
      const waited = await guard.randomDelay();
      console.log(`W${workerId} pausing ${(waited / 1000).toFixed(0)}s before the next profile`);
    }
  }

  await browser.close();
  fs.writeFileSync(outputFile, JSON.stringify(results, null, 2));
  releaseConcurrencyLock();
  console.log(`\nWorker ${workerId} completed: ${results.filter(r => r.confidence >= 50).length} verified out of ${targets.length}`);
}

run().catch((e) => {
  console.error(e);
  releaseConcurrencyLock();
  process.exit(1);
});
