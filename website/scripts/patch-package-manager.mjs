import {fileURLToPath} from 'node:url';
import {replaceBundledIpAddress} from '../lib/package-manager-security.mjs';

replaceBundledIpAddress(fileURLToPath(new URL('../', import.meta.url)));
// This verifies every locked dependency and executes the NAT64 regression
// against the package actually resolved by npm, before npm performs any work.
await import('./check-package-manager.mjs');
