#!/usr/bin/env node












'use strict';

module.exports = require('../li-safety.js');

if (require.main === module) {

  require('child_process');
  const { execFileSync } = require('child_process');
  const path = require('path');
  const canonical = path.join(__dirname, '..', 'li-safety.js');
  process.stdout.write(execFileSync(process.execPath, [canonical]).toString());
}
