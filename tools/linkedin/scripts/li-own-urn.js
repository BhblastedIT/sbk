// Your own LinkedIn member id: the ACoA... part of your profile URN (urn:li:fsd_profile:<id>). The browser
// scripts use it to build your mailbox URN and to tell your messages from the other person's.
//
// Where it comes from, in this order (nothing to edit in the scripts):
//   1. the environment variable SBK_LINKEDIN_OWN_URN (the id or the whole URN);
//   2. "linkedin": {"own_urn": "..."} in sbk.config.json (SBK_CONFIG, then <data root>/sbk.config.json, then the
//      repo root, the same order as tools/sbk_config.py);
//   3. the profile LinkedIn returns for your own login (/voyager/api/me), which the scripts already read.
const fs = require('fs');
const os = require('os');
const path = require('path');

function idFromUrn(value) {
  if (!value) return '';
  const m = String(value).match(/(ACoA[A-Za-z0-9_-]{10,})/);
  return m ? m[1] : '';
}

function configFiles() {
  const dataRoot = process.env.SBK_DATA_ROOT || path.join(os.homedir(), '.sbk-data');
  const repoRoot = path.resolve(__dirname, '..', '..', '..');
  return [process.env.SBK_CONFIG, path.join(dataRoot, 'sbk.config.json'), path.join(repoRoot, 'sbk.config.json')]
    .filter(Boolean);
}

function ownUrnFromConfig() {
  const fromEnv = idFromUrn(process.env.SBK_LINKEDIN_OWN_URN);
  if (fromEnv) return fromEnv;
  for (const file of configFiles()) {
    let cfg;
    try {
      cfg = JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch (e) {
      continue; // missing or unreadable: the next one
    }
    const id = idFromUrn(cfg && cfg.linkedin && cfg.linkedin.own_urn);
    if (id) return id;
  }
  return '';
}

// The id inside the answer of /voyager/api/me (normalized JSON): the MiniProfile of your own login.
function ownUrnFromMe(me) {
  if (!me) return '';
  const included = me.included || (me.data && me.data.included) || [];
  const mini = included.find((e) => String(e['$type'] || '').includes('MiniProfile'));
  if (mini) {
    const id = idFromUrn(mini.dashEntityUrn) || idFromUrn(mini.entityUrn) || idFromUrn(mini.objectUrn);
    if (id) return id;
  }
  const data = me.data || {};
  return idFromUrn(data['*miniProfile']) || idFromUrn(data.dashEntityUrn) || idFromUrn(data.entityUrn);
}

// Stops the script with a clear message when the id is still unknown.
function requireOwnUrn(id) {
  if (id) return id;
  console.error(
    'Cannot tell which LinkedIn member you are: LinkedIn did not return your profile. Set "linkedin": ' +
      '{"own_urn": "ACoA..."} in sbk.config.json (the id at the end of your profile URN) or SBK_LINKEDIN_OWN_URN.'
  );
  process.exit(2);
}

module.exports = { idFromUrn, ownUrnFromConfig, ownUrnFromMe, requireOwnUrn };
