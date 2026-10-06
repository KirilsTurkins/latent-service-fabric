import {createRequire} from 'node:module';
import path from 'node:path';
import {qualifyEmptyErrorOracle} from './empty-error-oracle.mjs';

const [toolchain, chrome] = process.argv.slice(2);
const {chromium} = createRequire(path.join(toolchain, 'package.json'))('playwright-core');
const browser = await chromium.launch({executablePath: chrome, headless: true,
  args: ['--no-proxy-server', ...(process.platform === 'linux' && process.getuid() === 0 ? ['--no-sandbox'] : [])]});
try { console.log(JSON.stringify(await qualifyEmptyErrorOracle(browser))); }
finally { await browser.close(); }
