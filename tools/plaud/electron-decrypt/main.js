const { app, safeStorage } = require('electron');
const fs = require('fs');
const os = require('os');
const path = require('path');

// The Plaud desktop app's own folder in your home.
const PLAUD_DIR = path.join(os.homedir(), 'Library', 'Application Support', 'Plaud');


app.setPath('userData', PLAUD_DIR);
app.name = 'Plaud';  // Match keychain "Plaud Safe Storage"

app.whenReady().then(async () => {
  try {

    if (!safeStorage.isEncryptionAvailable()) {
      console.error(JSON.stringify({ error: 'safeStorage not available' }));
      app.quit();
      return;
    }

    const encPath = path.join(PLAUD_DIR, 'encryption.json');
    const enc = JSON.parse(fs.readFileSync(encPath, 'utf8'));

    const result = {};
    for (const key of Object.keys(enc)) {
      try {
        const buf = Buffer.from(enc[key], 'base64');
        const decrypted = safeStorage.decryptString(buf);
        result[key] = decrypted;
      } catch (e) {
        result[key] = `ERR: ${e.message}`;
      }
    }

    console.log(JSON.stringify(result, null, 2));
  } catch (e) {
    console.error(JSON.stringify({ error: e.message, stack: e.stack }));
  }
  app.quit();
});
