#!/usr/bin/env node















































'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');




const MIN_DELAY_MS = 45000;          // floor between requests (jitter low bound)
const MAX_DELAY_MS = 120000;         // jitter high bound
const DANGER_ZONE_MS = 30000;        // below this is forbidden

const DEFAULT_SESSION_CAP = 30;      // max LinkedIn API calls per run
const DEFAULT_DAILY_CAP = 40;        // max LinkedIn API calls per local day

const BACKOFF_BASE_MS = 30000;       // transient backoff base
const BACKOFF_MULTIPLIER = 2.0;      // x2 each attempt
const BACKOFF_CAP_MS = 300000;       // 5 minutes hard cap
const BACKOFF_MAX_ATTEMPTS = 3;      // then abort the run
const BACKOFF_JITTER_FRACTION = 0.30; // +0..30% random jitter on backoff


const DATA_DIR = path.join(os.homedir(), '.sbk-data', 'linkedin');
const KILLSWITCH_LOCK = path.join(DATA_DIR, '.linkedin-killswitch');


const OK = 'OK';                 // valid data, proceed
const GONE = 'GONE';             // 404/400: missing/bad, skip item, continue
const TRANSIENT = 'TRANSIENT';   // 5xx / network error: eligible for backoff
const STOP = 'STOP';             // kill-switch condition: abort everything


const KILLSWITCH_BODY_MARKERS = [
  'temporarily restricted',
  'unusual activity',
  'software that automates activity',
  'captcha',
  'challenge',
  'visiting a very high number of pages',
  'request denied',
];


const KILLSWITCH_URL_PATTERNS = [
  /\/authwall/i,
  /\/checkpoint/i,
  /\/challenge/i,
  /\/uas\/login/i,
  /\/login/i,
];






function todayStr() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function dailyCapPath(day) {
  const d = day || todayStr();
  return path.join(DATA_DIR, `.li-daily-cap-${d}.json`);
}

function ensureDataDir() {
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  } catch (e) {

  }
}


function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}










function checkKillswitch() {
  if (fs.existsSync(KILLSWITCH_LOCK)) {
    let reason = 'unknown';
    let ts = 'unknown';
    try {
      const payload = JSON.parse(fs.readFileSync(KILLSWITCH_LOCK, 'utf8'));
      reason = payload.reason || reason;
      ts = payload.timestamp || ts;
    } catch (e) {
      reason = 'unknown (unreadable lock)';
    }
    process.stderr.write(
      '[li-safety] KILL-SWITCH ACTIVE. Refusing to start.\n' +
        `  lock:   ${KILLSWITCH_LOCK}\n` +
        `  reason: ${reason}\n` +
        `  since:  ${ts}\n` +
        '  Remove the lock manually (account owner) to resume.\n'
    );
    process.exit(2);
  }
}






function tripKillswitch(reason) {
  const payload = {
    reason: reason,
    timestamp: new Date().toISOString(),
    pid: process.pid,
    script: process.argv[1] || '?',
  };
  try {
    ensureDataDir();
    fs.writeFileSync(KILLSWITCH_LOCK, JSON.stringify(payload, null, 2));
  } catch (e) {
    process.stderr.write(
      `[li-safety] WARNING: could not write kill-switch lock: ${e}\n`
    );
  }
  process.stderr.write(
    `[li-safety] KILL-SWITCH TRIPPED: ${reason}\n` +
      `  Wrote lock: ${KILLSWITCH_LOCK}\n` +
      '  Aborting run (exit 2).\n'
  );
  process.exit(2);
}






function loadDailyCap(day) {
  const p = dailyCapPath(day);
  if (!fs.existsSync(p)) return 0;
  try {
    const data = JSON.parse(fs.readFileSync(p, 'utf8'));
    return parseInt(data.count, 10) || 0;
  } catch (e) {

    return 0;
  }
}


function saveDailyCap(count, day) {
  const d = day || todayStr();
  const p = dailyCapPath(d);
  const payload = {
    date: d,
    count: parseInt(count, 10) || 0,
    updated_at: new Date().toISOString(),
  };
  try {
    ensureDataDir();
    fs.writeFileSync(p, JSON.stringify(payload, null, 2));
  } catch (e) {
    process.stderr.write(
      `[li-safety] WARNING: could not persist daily counter: ${e}\n`
    );
  }
}










function looksLikeHtml(lowBody) {
  if (!lowBody) return false;
  const stripped = lowBody.replace(/^\s+/, '');
  if (stripped.startsWith('{') || stripped.startsWith('[')) return false;
  const head = stripped.slice(0, 4096);
  const markers = ['<!doctype html', '<html', '<head', '<body', '<script'];
  return markers.some((m) => head.indexOf(m) !== -1);
}










function classifyResponse(res, bodyText) {
  const body = typeof bodyText === 'string' ? bodyText : bodyText == null ? '' : String(bodyText);
  const lowBody = body.toLowerCase();
  const url = (res && (res.url || res.finalUrl)) || '';


  if (!res || res.status == null) {
    return TRANSIENT;
  }

  let status = parseInt(res.status, 10);
  if (Number.isNaN(status)) return TRANSIENT;


  if (status === 429) tripKillswitch('HTTP 429 Too Many Requests');
  if (status === 999) tripKillswitch('HTTP 999 Request Denied (LinkedIn IP/edge block)');
  if (status === 403) tripKillswitch('HTTP 403 on data endpoint (suspect/restricted session)');


  if ([301, 302, 303, 307, 308].indexOf(status) !== -1) {
    for (const pat of KILLSWITCH_URL_PATTERNS) {
      if (pat.test(url)) {
        tripKillswitch(`Redirect ${status} to authwall/login/checkpoint: ${url}`);
      }
    }
    tripKillswitch(`Unexpected redirect ${status} on Voyager/Sales-Nav endpoint: ${url}`);
  }


  for (const pat of KILLSWITCH_URL_PATTERNS) {
    if (pat.test(url)) {
      tripKillswitch(`Authwall/checkpoint/challenge URL: ${url}`);
    }
  }


  for (const marker of KILLSWITCH_BODY_MARKERS) {
    if (lowBody.indexOf(marker) !== -1) {
      tripKillswitch(`Body marker detected: '${marker}'`);
    }
  }


  if (status === 200) {
    if (looksLikeHtml(lowBody)) {
      tripKillswitch('HTTP 200 with HTML/non-JSON body (masked challenge/authwall)');
    }
    return OK;
  }


  if (status === 400 || status === 404) {
    return GONE;
  }


  if (status >= 500 && status <= 599) {
    return TRANSIENT;
  }


  tripKillswitch(`Unexpected non-200 response (${status}) on Voyager/Sales-Nav endpoint`);
  return STOP; // unreachable (tripKillswitch exits), kept for clarity
}









class LinkedInSafetyGuard {





  constructor(opts) {
    const o = opts || {};
    const sessionCap = o.sessionCap == null ? DEFAULT_SESSION_CAP : o.sessionCap;
    if (sessionCap > DEFAULT_SESSION_CAP) {
      throw new Error(
        `sessionCap ${sessionCap} exceeds policy max ${DEFAULT_SESSION_CAP}; ` +
          "raising requires an explicit override + the account owner's confirmation"
      );
    }
    this.sessionCap = sessionCap;
    this.dailyCap = o.dailyCap == null ? DEFAULT_DAILY_CAP : o.dailyCap;
    this.sessionCalls = 0;
    this._transientAttempt = 0;
    ensureDataDir();
    checkKillswitch(); // refuse to start if a kill-switch lock exists
  }

  checkKillswitch() {
    checkKillswitch();
  }

  tripKillswitch(reason) {
    tripKillswitch(reason);
  }

  loadDailyCap(day) {
    return loadDailyCap(day);
  }

  saveDailyCap(count, day) {
    saveDailyCap(count, day);
  }


  assertUnderCaps() {
    if (this.sessionCalls >= this.sessionCap) {
      throw new Error(
        `session cap reached (${this.sessionCalls}/${this.sessionCap}). Stop this run.`
      );
    }
    const daily = loadDailyCap();
    if (daily >= this.dailyCap) {
      throw new Error(
        `daily cap reached (${daily}/${this.dailyCap}) for ${todayStr()}. Resume tomorrow.`
      );
    }
  }






  recordCall() {
    this.sessionCalls += 1;
    const daily = loadDailyCap();
    saveDailyCap(daily + 1);
  }





  async randomDelay() {
    let delay = MIN_DELAY_MS + Math.random() * (MAX_DELAY_MS - MIN_DELAY_MS);
    if (delay < DANGER_ZONE_MS) delay = DANGER_ZONE_MS; // defensive
    await sleep(delay);
    return delay;
  }


  resetTransientBackoff() {
    this._transientAttempt = 0;
  }







  async expBackoffTransient() {
    if (this._transientAttempt >= BACKOFF_MAX_ATTEMPTS) {
      throw new Error(
        `transient backoff exhausted after ${BACKOFF_MAX_ATTEMPTS} attempts; aborting run`
      );
    }
    const n = this._transientAttempt;
    this._transientAttempt += 1;
    let base = BACKOFF_BASE_MS * Math.pow(BACKOFF_MULTIPLIER, n);
    base = Math.min(base, BACKOFF_CAP_MS);
    const jitter = base * (Math.random() * BACKOFF_JITTER_FRACTION);
    const delay = Math.min(base + jitter, BACKOFF_CAP_MS);
    await sleep(delay);
    return delay;
  }

  classifyResponse(res, bodyText) {
    return classifyResponse(res, bodyText);
  }
}

module.exports = {
  LinkedInSafetyGuard,

  loadDailyCap,
  saveDailyCap,
  checkKillswitch,
  tripKillswitch,
  classifyResponse,

  OK,
  GONE,
  TRANSIENT,
  STOP,
  MIN_DELAY_MS,
  MAX_DELAY_MS,
  DEFAULT_SESSION_CAP,
  DEFAULT_DAILY_CAP,
  KILLSWITCH_LOCK,
  DATA_DIR,
  todayStr,
  sleep,
};





module.exports.assertUnderCaps = function (guard) {
  return guard.assertUnderCaps();
};
module.exports.randomDelay = function (guard) {
  return guard
    ? guard.randomDelay()
    : (async () => {
        let delay = MIN_DELAY_MS + Math.random() * (MAX_DELAY_MS - MIN_DELAY_MS);
        if (delay < DANGER_ZONE_MS) delay = DANGER_ZONE_MS;
        await sleep(delay);
        return delay;
      })();
};
module.exports.expBackoffTransient = function (guard) {
  return guard.expBackoffTransient();
};


if (require.main === module) {
  const assert = require('assert');
  assert.strictEqual(
    classifyResponse({ status: 200, url: 'https://www.linkedin.com/voyager/api/x' }, '{"data":1}'),
    OK
  );
  assert.strictEqual(classifyResponse({ status: 404, url: 'x' }, ''), GONE);
  assert.strictEqual(classifyResponse({ status: 503, url: 'x' }, ''), TRANSIENT);
  assert.strictEqual(classifyResponse(null, null), TRANSIENT);
  process.stdout.write('li-safety self-test OK (no LinkedIn calls made)\n');
}
