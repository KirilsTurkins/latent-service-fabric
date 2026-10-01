import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const require = createRequire(import.meta.url);

/** @returns {import('@docusaurus/types').Plugin} */
export default function codeWordWrap() {
  const lib = path.dirname(require.resolve('@docusaurus/theme-common'));
  const metadata = JSON.parse(fs.readFileSync(path.join(lib, '../package.json'), 'utf8'));
  if (metadata.version !== '3.10.2') throw new Error('Review the code-word-wrap fix on a Docusaurus pin refresh');
  const hook = path.join(lib, 'hooks/useCodeWordWrap.js');
  const loader = fileURLToPath(new URL('./code-word-wrap-loader.cjs', import.meta.url));
  return {
    name: 'lsf-code-word-wrap-lifecycle',
    configureWebpack() {
      return {module: {rules: [{include: [hook], enforce: 'pre', loader}]}};
    },
  };
}
