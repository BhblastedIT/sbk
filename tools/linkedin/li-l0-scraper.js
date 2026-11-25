#!/usr/bin/env node











































const fs = require('fs');
const path = require('path');
const safety = require('./li-safety.js');



const PROJECT_DIR = path.join(__dirname, '..', '..');
const SESSION_FILE = process.env.LINKEDIN_SESSION
  || path.join(PROJECT_DIR, 'sbk', 'raw', 'linkedin', 'linkedin-session.json');

const SBK_DATA = path.join(process.env.HOME, '.sbk-data', 'linkedin');
const INPUT_FILE = path.join(SBK_DATA, 'raw', 'profile-urls-to-scrape.json');
const OUTPUT_FILE = path.join(SBK_DATA, 'raw', 'profiles-enriched.json');
const CHECKPOINT_FILE = path.join(SBK_DATA, 'raw', '.profiles-checkpoint.json');

const VOYAGER_BASE = 'https://www.linkedin.com/voyager/api';
const MY_URN = 'ACoAAEXAMPLE_URN_PLACEHOLDER';







const BATCH_SIZE = 10;             // calls per batch before an extra cooldown
const BATCH_PAUSE = 120000;        // 120s extra pause between batches (on top of per-call delay)
const PROGRESS_EVERY = 5;          // Log every N profiles
const CHECKPOINT_EVERY = 5;        // Save checkpoint every N profiles



function loadSession() {
  if (!fs.existsSync(SESSION_FILE)) {
    console.error(`Session file not found: ${SESSION_FILE}`);
    console.error('Ensure linkedin-session.json exists with active cookies.');
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
const ts = () => new Date().toISOString().substring(11, 19);

function ensureDir(dirPath) {
  if (!fs.existsSync(dirPath)) fs.mkdirSync(dirPath, { recursive: true });
}














let totalRateLimits = 0;   // retained for log compatibility; kill-switch makes this 0/1
let totalErrors = 0;








async function apiFetch(url, headers, guard) {


  for (;;) {

    guard.assertUnderCaps();


    await guard.randomDelay();

    let res = null;
    let bodyText = '';
    try {
      res = await fetch(url, { headers, redirect: 'follow' });

      guard.recordCall();


      bodyText = await res.text();
    } catch (e) {

      guard.recordCall();
      totalErrors++;
      try {
        await guard.expBackoffTransient();
        continue;
      } catch (abort) {
        return { error: 'transient_exhausted', status: null };
      }
    }



    const verdict = guard.classifyResponse(res, bodyText);

    if (verdict === safety.OK) {
      guard.resetTransientBackoff();
      try {
        return JSON.parse(bodyText);
      } catch (e) {


        totalErrors++;
        try {
          await guard.expBackoffTransient();
          continue;
        } catch (abort) {
          return { error: 'bad_json', status: res.status };
        }
      }
    }

    if (verdict === safety.GONE) {
      return { error: 'gone', status: res.status };
    }

    if (verdict === safety.TRANSIENT) {
      totalErrors++;
      try {
        await guard.expBackoffTransient();
        continue;
      } catch (abort) {
        return { error: 'transient_exhausted', status: res.status };
      }
    }


    return { error: 'stopped', status: res ? res.status : null };
  }
}







function extractLinkedInId(url) {
  if (!url) return null;

  const match = url.match(/(ACoAA[A-Za-z0-9_-]+)/);
  return match ? match[1] : null;
}










async function fetchProfileByUrn(linkedinId, headers, guard) {
  const profileUrl = `${VOYAGER_BASE}/identity/dash/profiles?q=memberIdentity&memberIdentity=${linkedinId}&decorationId=com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93`;
  const data = await apiFetch(profileUrl, headers, guard);

  if (data && !data.error) {
    const profile = parseProfileResponse(data, linkedinId);
    if (profile && profile.name) return profile;
  }
  return null;
}





function parseProfileResponse(data, linkedinId) {
  const included = data.included || data.elements || [];
  if (!Array.isArray(included) || included.length === 0) {

    if (data.elements && Array.isArray(data.elements)) {
      return parseProfileElements(data.elements, linkedinId);
    }
    return null;
  }

  let name = '';
  let headline = '';
  let location = '';
  let company = '';
  let about = '';
  let vanityUrl = '';
  let profilePictureUrl = '';
  let industry = '';
  let degree = '';
  let publicProfileUrl = '';

  for (const entity of included) {
    const type = entity['$type'] || entity._type || '';


    if (type.includes('MiniProfile') || type.includes('miniProfile')) {
      if (!name && entity.firstName && entity.lastName) {
        name = `${entity.firstName} ${entity.lastName}`.trim();
      }
      if (!headline && entity.occupation) headline = entity.occupation;
      if (!vanityUrl && entity.publicIdentifier) vanityUrl = entity.publicIdentifier;
      if (!profilePictureUrl && entity.picture) {
        profilePictureUrl = extractPictureUrl(entity.picture);
      }
    }


    if (type.includes('Profile') && !type.includes('Mini')) {
      if (!name && entity.firstName && entity.lastName) {
        name = `${entity.firstName} ${entity.lastName}`.trim();
      }
      if (!headline && entity.headline) headline = entity.headline;
      if (!location && entity.locationName) location = entity.locationName;
      if (!location && entity.geoLocationName) location = entity.geoLocationName;
      if (!vanityUrl && entity.publicIdentifier) vanityUrl = entity.publicIdentifier;
      if (!industry && entity.industryName) industry = entity.industryName;
      if (!profilePictureUrl && entity.profilePicture) {
        profilePictureUrl = extractPictureUrl(entity.profilePicture);
      }
    }


    if (type.includes('dash') && type.includes('Profile')) {
      if (!name && entity.firstName && entity.lastName) {
        name = `${entity.firstName} ${entity.lastName}`.trim();
      }
      if (!headline && entity.headline) headline = entity.headline;
      if (!location && entity.geoLocation?.geo?.defaultLocalizedName) {
        location = entity.geoLocation.geo.defaultLocalizedName;
      }
      if (!location && entity.locationName) location = entity.locationName;
      if (!vanityUrl && entity.publicIdentifier) vanityUrl = entity.publicIdentifier;
      if (!industry && entity.industryName) industry = entity.industryName;
      if (!profilePictureUrl && entity.profilePicture?.displayImageReference?.vectorImage) {
        profilePictureUrl = extractVectorImageUrl(entity.profilePicture.displayImageReference.vectorImage);
      }
    }


    if ((type.includes('Position') || type.includes('position')) && !company) {
      const isCurrent = entity.timePeriod?.endDate === undefined || entity.dateRange?.end === undefined;
      if (isCurrent || !entity.timePeriod) {
        company = entity.companyName || entity.company?.name || '';
      }
    }


    if (type.includes('Summary') || type.includes('summary')) {
      if (!about && entity.text) about = entity.text.substring(0, 500);
    }


    if (type.includes('TopPosition') || type.includes('topPosition')) {
      if (!company) {
        company = entity.companyName || entity.company || '';
        if (typeof company === 'object') company = company.name || '';
      }
    }


    if (type.includes('GeoLocation') || type.includes('Location')) {
      if (!location && entity.defaultLocalizedName) location = entity.defaultLocalizedName;
      if (!location && entity.defaultLocalizedNameWithoutCountryName) {
        location = entity.defaultLocalizedNameWithoutCountryName;
      }
    }


    if (type.includes('NetworkInfo') || type.includes('networkInfo')) {
      if (!degree && entity.distance) degree = entity.distance.value || '';
    }
  }


  if (!about) {
    for (const entity of included) {
      if (entity.summary && typeof entity.summary === 'string' && entity.summary.length > 10) {
        about = entity.summary.substring(0, 500);
        break;
      }
    }
  }


  if (vanityUrl) {
    publicProfileUrl = `https://www.linkedin.com/in/${vanityUrl}`;
  }

  if (!name) return null;

  return {
    linkedin_id: linkedinId,
    name,
    headline: headline || '',
    company: company || '',
    location: location || '',
    about: about || '',
    vanity_url: vanityUrl || '',
    public_profile_url: publicProfileUrl || '',
    profile_picture_url: profilePictureUrl || '',
    industry: industry || '',
    degree: degree || '',
  };
}




function parseProfileElements(elements, linkedinId) {
  for (const elem of elements) {
    const firstName = elem.firstName || '';
    const lastName = elem.lastName || '';
    if (firstName || lastName) {
      return {
        linkedin_id: linkedinId,
        name: `${firstName} ${lastName}`.trim(),
        headline: elem.headline || '',
        company: '',
        location: elem.geoLocation?.geo?.defaultLocalizedName || elem.locationName || '',
        about: '',
        vanity_url: elem.publicIdentifier || '',
        public_profile_url: elem.publicIdentifier ? `https://www.linkedin.com/in/${elem.publicIdentifier}` : '',
        profile_picture_url: '',
        industry: elem.industryName || '',
        degree: '',
      };
    }
  }
  return null;
}




function parseMiniProfileResponse(data, linkedinId) {

  const profile = data.profile || {};
  const included = data.included || [];

  let name = '';
  let headline = '';
  let location = '';
  let company = '';
  let about = '';
  let vanityUrl = '';
  let profilePictureUrl = '';
  let industry = '';


  if (profile.firstName || profile.lastName) {
    name = `${profile.firstName || ''} ${profile.lastName || ''}`.trim();
    headline = profile.headline || profile.occupation || '';
    location = profile.locationName || profile.geoLocationName || '';
    vanityUrl = profile.publicIdentifier || '';
    industry = profile.industryName || '';
    about = profile.summary || '';
    if (about.length > 500) about = about.substring(0, 500);
  }


  for (const entity of included) {
    const type = entity['$type'] || '';

    if (type.includes('MiniProfile') || type.includes('Profile')) {
      if (!name && entity.firstName) {
        name = `${entity.firstName} ${entity.lastName || ''}`.trim();
      }
      if (!headline && (entity.headline || entity.occupation)) {
        headline = entity.headline || entity.occupation;
      }
      if (!vanityUrl && entity.publicIdentifier) vanityUrl = entity.publicIdentifier;
      if (!location && (entity.locationName || entity.geoLocationName)) {
        location = entity.locationName || entity.geoLocationName;
      }
    }

    if (type.includes('Position') && !company) {
      const noEnd = !entity.timePeriod?.endDate;
      if (noEnd) company = entity.companyName || '';
    }
  }


  if (!company && data.positionGroupView?.elements) {
    for (const group of data.positionGroupView.elements) {
      const positions = group.positions || group.profilePositionInPositionGroup?.elements || [];
      for (const pos of positions) {
        if (!pos.timePeriod?.endDate) {
          company = pos.companyName || pos.company?.name || '';
          if (company) break;
        }
      }
      if (company) break;
    }
  }

  if (!name) return null;

  return {
    linkedin_id: linkedinId,
    name,
    headline: headline || '',
    company: company || '',
    location: location || '',
    about: about.substring(0, 500) || '',
    vanity_url: vanityUrl || '',
    public_profile_url: vanityUrl ? `https://www.linkedin.com/in/${vanityUrl}` : '',
    profile_picture_url: profilePictureUrl || '',
    industry: industry || '',
    degree: '',
  };
}




function extractPictureUrl(pictureObj) {
  if (!pictureObj) return '';


  if (pictureObj['com.linkedin.common.VectorImage']) {
    return extractVectorImageUrl(pictureObj['com.linkedin.common.VectorImage']);
  }


  if (pictureObj.displayImageReference?.vectorImage) {
    return extractVectorImageUrl(pictureObj.displayImageReference.vectorImage);
  }


  if (pictureObj.artifacts || pictureObj.rootUrl) {
    return extractVectorImageUrl(pictureObj);
  }

  return '';
}

function extractVectorImageUrl(vectorImage) {
  if (!vectorImage) return '';
  const rootUrl = vectorImage.rootUrl || '';
  const artifacts = vectorImage.artifacts || [];


  if (rootUrl && artifacts.length > 0) {
    const sorted = [...artifacts].sort((a, b) => (b.width || 0) - (a.width || 0));
    const best = sorted[0];
    return rootUrl + (best.fileIdentifyingUrlPathSegment || '');
  }

  return '';
}







async function fetchProfileViaSalesNav(linkedinId, headers, guard) {

  const snHeaders = { ...headers };
  const url = `https://www.linkedin.com/sales-api/salesApiProfiles/(profileId:${linkedinId},authType:NAME_SEARCH,authToken:)?decoration=%28entityUrn%2CfirstName%2ClastName%2CfullName%2Cheadline%2CmemberBadges%2Cdegree%2CprofilePictureDisplayImage%2CpendingInvitation%2CunlockHighlight%2CnumOfConnections%2CcrmStatus%2CsavedLead%2CdefaultPosition%2CgeoRegion%2ClistCount%2CflagshipProfileUrl%2Csummary%29`;

  const data = await apiFetch(url, snHeaders, guard);
  if (data && !data.error) {
    return parseSalesNavProfile(data, linkedinId);
  }
  return null;
}

function parseSalesNavProfile(data, linkedinId) {

  const profile = data.data || data;

  const name = profile.fullName || `${profile.firstName || ''} ${profile.lastName || ''}`.trim();
  if (!name) return null;

  return {
    linkedin_id: linkedinId,
    name,
    headline: profile.headline || '',
    company: profile.defaultPosition?.companyName || '',
    location: profile.geoRegion || '',
    about: (profile.summary || '').substring(0, 500),
    vanity_url: extractVanityFromFlagship(profile.flagshipProfileUrl),
    public_profile_url: profile.flagshipProfileUrl || '',
    profile_picture_url: extractVectorImageUrl(profile.profilePictureDisplayImage),
    industry: '',
    degree: profile.degree?.value || '',
    source_api: 'sales-navigator',
  };
}

function extractVanityFromFlagship(url) {
  if (!url) return '';
  const match = url.match(/linkedin\.com\/in\/([^/?]+)/);
  return match ? match[1] : '';
}



function loadExistingProfiles() {
  if (fs.existsSync(OUTPUT_FILE)) {
    try {
      const data = JSON.parse(fs.readFileSync(OUTPUT_FILE, 'utf8'));
      return data.profiles || [];
    } catch (e) {
      console.log(`  Warning: Could not parse existing ${OUTPUT_FILE}, starting fresh.`);
    }
  }
  return [];
}

function loadCheckpoint() {
  if (fs.existsSync(CHECKPOINT_FILE)) {
    try {
      return JSON.parse(fs.readFileSync(CHECKPOINT_FILE, 'utf8'));
    } catch (e) {}
  }
  return null;
}

function saveCheckpoint(scrapedIds, failedIds) {
  fs.writeFileSync(CHECKPOINT_FILE, JSON.stringify({
    scrapedIds: [...scrapedIds],
    failedIds: [...failedIds],
    savedAt: new Date().toISOString(),
  }));
}

function saveOutput(profiles, stats) {
  const output = {
    generated: new Date().toISOString(),
    scraper_version: 'linkedin-profile-scraper-v1',
    stats,
    profiles,
  };
  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
}



async function main() {
  const args = process.argv.slice(2);
  const limitArg = args.find(a => a.startsWith('--limit'));
  const limit = limitArg ? parseInt(args[args.indexOf(limitArg) + 1] || args[0]?.split('=')[1]) : 0;
  const useSalesNav = args.includes('--use-sales-nav');
  const salesNavAck = args.includes('--i-understand-salesnav-risk');
  const resume = args.includes('--resume');


  const live = args.includes('--live');
  const dryRun = args.includes('--dry-run') || !live;

  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║  SBK — LinkedIn Profile Scraper                      ║');
  console.log('║  Voyager API + Session Cookies (shared safety policy)   ║');
  console.log('╚══════════════════════════════════════════════════════════╝\n');



  safety.checkKillswitch();


  if (useSalesNav && !salesNavAck) {
    console.error(
      '\n  REFUSING: --use-sales-nav hits /sales-api/salesApiProfiles, the same\n' +
      '  endpoint that is known to trigger account restrictions. Re-run with --i-understand-salesnav-risk\n' +
      '  to confirm you accept the risk, or drop --use-sales-nav to use Voyager only.'
    );
    process.exit(1);
  }



  const policyCap = safety.DEFAULT_SESSION_CAP;
  let sessionCap = policyCap;
  if (limit > 0 && limit < policyCap) sessionCap = limit;
  if (limit > policyCap) {
    console.log(
      `  NOTE: --limit ${limit} exceeds the session cap (${policyCap}); ` +
      `capping this run at ${policyCap}. --limit can only lower it.`
    );
  }
  const guard = new safety.LinkedInSafetyGuard({ sessionCap });


  const session = loadSession();
  const headers = makeHeaders(session);
  console.log(`  Session loaded from: ${SESSION_FILE}`);
  console.log(`  Mode: ${live ? 'LIVE' : 'DRY RUN (no LinkedIn calls)'}`);
  console.log(`  Caps: session ${guard.sessionCap}, daily ${guard.dailyCap} ` +
    `(used today: ${safety.loadDailyCap()})`);


  if (!dryRun) {

    console.log('  Verifying session...');
    const me = await apiFetch(`${VOYAGER_BASE}/me`, headers, guard);
    if (!me || me.error) {
      console.error('\n  ERROR: Session expired or invalid. Re-login to LinkedIn in Chrome.');
      process.exit(1);
    }
    const myProfile = (me.included || []).find(e => (e['$type'] || '').includes('MiniProfile'));
    console.log(`  Logged in as: ${myProfile?.firstName} ${myProfile?.lastName}\n`);
  }


  if (!fs.existsSync(INPUT_FILE)) {
    console.error(`  ERROR: Input file not found: ${INPUT_FILE}`);
    console.error('  Run first: python3 tools/linkedin-extract-urls.py');
    process.exit(1);
  }

  const input = JSON.parse(fs.readFileSync(INPUT_FILE, 'utf8'));
  let profilesToScrape = input.profiles || [];
  console.log(`  Profiles to scrape: ${profilesToScrape.length}`);


  const existingProfiles = loadExistingProfiles();
  const scrapedIds = new Set(existingProfiles.map(p => p.linkedin_id));
  const failedIds = new Set();


  if (resume) {
    const checkpoint = loadCheckpoint();
    if (checkpoint) {
      for (const id of (checkpoint.scrapedIds || [])) scrapedIds.add(id);
      for (const id of (checkpoint.failedIds || [])) failedIds.add(id);
      console.log(`  Resuming: ${scrapedIds.size} already scraped, ${failedIds.size} failed`);
    }
  }


  const remaining = profilesToScrape.filter(p => {
    const id = extractLinkedInId(p.linkedin_url) || p.linkedin_id;
    return id && !scrapedIds.has(id);
  });

  console.log(`  Already scraped: ${scrapedIds.size}`);
  console.log(`  Remaining: ${remaining.length}`);





  const remainingDailyBudget = Math.max(0, guard.dailyCap - safety.loadDailyCap());
  const runCeiling = Math.max(0, Math.min(guard.sessionCap, remainingDailyBudget));
  const batch = remaining.slice(0, runCeiling);
  console.log(`  Will attempt: ${batch.length} (run ceiling ${runCeiling} = ` +
    `min session ${guard.sessionCap}, daily-left ${remainingDailyBudget})`);

  if (dryRun) {
    console.log('\n  [DRY RUN] No LinkedIn calls made. Would attempt these profiles:');
    for (const p of batch.slice(0, 20)) {
      console.log(`    ${p.name} (${p.total_messages} msgs) — ${p.linkedin_url.substring(0, 70)}`);
    }
    if (batch.length > 20) console.log(`    ... and ${batch.length - 20} more`);
    console.log('\n  Re-run with --live to perform the run (conservative caps + kill-switch apply).');
    return;
  }

  if (batch.length === 0) {
    console.log('\n  Nothing to scrape. All profiles already done!');
    return;
  }


  ensureDir(path.dirname(OUTPUT_FILE));


  console.log(`\n${'═'.repeat(60)}`);
  console.log(`  Starting profile scraping (${batch.length} profiles)`);
  console.log(`  Rate: shared safety delay ${safety.MIN_DELAY_MS / 1000}-${safety.MAX_DELAY_MS / 1000}s/call, ` +
    `${BATCH_SIZE}/batch + ${BATCH_PAUSE / 1000}s cooldown`);
  console.log(`${'═'.repeat(60)}\n`);

  const allProfiles = [...existingProfiles];
  let scraped = 0;
  let successful = 0;
  let failed = 0;
  let notFound = 0;
  const startTime = Date.now();

  for (let i = 0; i < batch.length; i++) {
    const profile = batch[i];
    const linkedinId = extractLinkedInId(profile.linkedin_url) || profile.linkedin_id;

    if (!linkedinId || linkedinId === 'linkedin member') {
      failed++;
      continue;
    }




    let result = null;
    if (useSalesNav) {
      result = await fetchProfileViaSalesNav(linkedinId, headers, guard);
      if (result) result.source_api = 'sales-navigator';
    } else {
      result = await fetchProfileByUrn(linkedinId, headers, guard);
      if (result) result.source_api = 'voyager';
    }

    scraped++;

    if (result) {

      result.original_name = profile.name;
      result.original_url = profile.linkedin_url;
      result.total_messages = profile.total_messages;
      result.scraped_at = new Date().toISOString();

      allProfiles.push(result);
      scrapedIds.add(linkedinId);
      successful++;
    } else {
      failedIds.add(linkedinId);
      failed++;


      notFound++;
    }


    if (scraped % PROGRESS_EVERY === 0 || scraped === batch.length) {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
      const rate = (scraped / (elapsed || 1)).toFixed(1);
      const eta = batch.length > scraped
        ? (((batch.length - scraped) / (rate || 0.1)) / 60).toFixed(1)
        : '0';
      console.log(
        `  [${ts()}] ${scraped}/${batch.length} | ` +
        `OK: ${successful} | FAIL: ${failed} | ` +
        `Rate: ${rate}/s | ETA: ${eta}min | ` +
        `429s: ${totalRateLimits}`
      );
    }


    if (scraped % CHECKPOINT_EVERY === 0) {
      saveOutput(allProfiles, {
        totalScraped: allProfiles.length,
        thisRunScraped: scraped,
        thisRunSuccessful: successful,
        thisRunFailed: failed,
        rateLimits: totalRateLimits,
      });
      saveCheckpoint(scrapedIds, failedIds);
    }





    if (scraped > 0 && scraped % BATCH_SIZE === 0 && i < batch.length - 1) {
      console.log(`\n  [${ts()}] Batch of ${BATCH_SIZE} complete. Extra cooldown ${BATCH_PAUSE / 1000}s...\n`);
      await delay(BATCH_PAUSE + Math.random() * 10000);
    }
  }


  const stats = {
    totalProfilesEnriched: allProfiles.length,
    thisRun: {
      attempted: batch.length,
      scraped,
      successful,
      failed,
      notFound,
      rateLimitsHit: totalRateLimits,
      totalErrors: totalErrors,
      durationSeconds: Math.round((Date.now() - startTime) / 1000),
    },
  };

  saveOutput(allProfiles, stats);


  if (fs.existsSync(CHECKPOINT_FILE)) {
    fs.unlinkSync(CHECKPOINT_FILE);
  }


  console.log(`\n${'═'.repeat(60)}`);
  console.log('  PROFILE SCRAPING COMPLETE');
  console.log('═'.repeat(60));
  console.log(`  Total profiles enriched: ${allProfiles.length}`);
  console.log(`  This run: ${scraped} attempted`);
  console.log(`    Successful: ${successful}`);
  console.log(`    Failed: ${failed}`);
  console.log(`    Not found: ${notFound}`);
  console.log(`    Rate limits: ${totalRateLimits}`);
  console.log(`  Duration: ${stats.thisRun.durationSeconds}s`);
  console.log(`  Output: ${OUTPUT_FILE}`);
  console.log(`  Size: ${(fs.statSync(OUTPUT_FILE).size / 1024).toFixed(1)} KB`);
  console.log('═'.repeat(60) + '\n');


  const recent = allProfiles.slice(-5);
  if (recent.length > 0) {
    console.log('  Last 5 scraped profiles:');
    for (const p of recent) {
      console.log(`    ${p.name} | ${p.headline.substring(0, 50)} | ${p.company} | ${p.location}`);
      if (p.vanity_url) console.log(`      -> linkedin.com/in/${p.vanity_url}`);
    }
  }
}

main().catch(e => {
  console.error('\nFATAL:', e.message);
  console.error(e.stack);
  process.exit(1);
});
