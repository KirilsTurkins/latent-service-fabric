import type {Config} from '@docusaurus/types';
import type {Options, ThemeConfig} from '@docusaurus/preset-classic';
import path from 'node:path';
import {prepare} from './lib/prepare.mjs';
import {repositoryUrl, sha256, websiteRoot} from './lib/repository.mjs';
import {remarkRepositoryLinks, rehypeRepositoryLinks} from './plugins/repository-links.mjs';
import {remarkExamples} from './plugins/examples/remark.mjs';
import {mermaidOptions, preparePalette, prismTheme} from './lib/palette.mjs';

const prepared = prepare();
type Snapshot = {index: typeof prepared.index & {documentPrefix: string}; assets: typeof prepared.assets;
  examples: typeof prepared.examples; manifest: {runtimeVersion: string}};
const snapshots = prepared.snapshots as Snapshot[];
const theme = preparePalette();
function selected(file: {path: string}) {
  const name = file.path.replaceAll('\\', '/');
  const snapshot = snapshots.find(item => name.includes(`/${item.index.documentPrefix}/`));
  if (name.includes('/versioned_docs/') && !snapshot) throw new Error('Unregistered document version');
  return snapshot ?? {index: prepared.index, assets: prepared.currentAssets, examples: prepared.examples};
}
const repositoryRemark = () => (tree: unknown, file: {path: string}) => remarkRepositoryLinks({...selected(file), baseUrl: prepared.baseUrl})(tree, file);
const repositoryRehype = () => (tree: unknown, file: {path: string}) => rehypeRepositoryLinks({...selected(file), baseUrl: prepared.baseUrl})(tree, file);
const examplesRemark = () => (tree: unknown, file: {path: string}) => {
  const version = selected(file);
  return remarkExamples({bundle: version.examples.bundle, documentVersion: version.index.channel})(tree);
};
const inputIdentity = {fingerprint: sha256(JSON.stringify({revision: prepared.index.revision, pages: prepared.manifest.pages, assets: prepared.assets, baseUrl: prepared.baseUrl, examples: prepared.examples.identity, versions: prepared.manifest.versions}))};
const commonDocs = {
  numberPrefixParser: false as const,
  beforeDefaultRemarkPlugins: [[repositoryRemark, inputIdentity], [examplesRemark, inputIdentity]],
  beforeDefaultRehypePlugins: [[repositoryRehype, inputIdentity]],
  showLastUpdateAuthor: false,
  showLastUpdateTime: false,
};

const config: Config = {
  title: 'Latent Service Fabric',
  tagline: 'Source-backed documentation, with explicit support boundaries',
  url: process.env.LSF_SITE_URL ?? 'https://kirilsturkins.github.io',
  baseUrl: prepared.baseUrl,
  trailingSlash: true,
  organizationName: 'KirilsTurkins',
  projectName: 'latent-service-fabric',
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',
  staticDirectories: [path.relative(websiteRoot, prepared.staticDirectory).split(path.sep).join('/')],
  markdown: {format: 'detect', mermaid: true, mdx1Compat: {comments: false}, hooks: {onBrokenMarkdownLinks: 'throw', onBrokenMarkdownImages: 'throw'}},
  customFields: {contentIdentity: {channel: 'development', revision: prepared.index.revision, dirty: prepared.manifest.dirty}, publications: prepared.manifest.versions},
  presets: [['classic', {
    docs: {
      ...commonDocs,
      path: '../docs',
      routeBasePath: 'docs',
      exclude: ['wiki/**'],
      sidebarPath: './sidebars.ts',
      lastVersion: 'current',
      versions: {current: {label: 'Development', path: '', banner: 'none'}, ...Object.fromEntries(snapshots.map(snapshot => [snapshot.index.channel,
        {label: `${snapshot.manifest.runtimeVersion} (alpha)`, path: snapshot.index.channel, banner: 'none'}]))},
      editUrl: ({docPath, version}: {docPath: string; version: string}) => `${repositoryUrl}/edit/${version === 'current' ? prepared.index.revision : snapshots.find(snapshot => snapshot.index.channel === version)!.index.revision}/docs/${docPath}`,
    },
    blog: false,
    theme: {customCss: [theme.css, './src/css/foundation.css', './src/css/theme.css']},
  } satisfies Options]],
  plugins: [
    ['@docusaurus/plugin-content-docs', {
      ...commonDocs,
      id: 'decisions',
      path: '../adr',
      routeBasePath: 'decisions',
      editUrl: ({docPath}: {docPath: string}) => `${repositoryUrl}/edit/${prepared.index.revision}/adr/${docPath}`,
    }],
    './plugins/repository-content.mjs',
    './plugins/examples/index.mjs',
    './plugins/discovery.mjs',
  ],
  themes: ['@docusaurus/theme-mermaid'],
  themeConfig: {
    colorMode: {defaultMode: 'light', respectPrefersColorScheme: true},
    mermaid: {theme: {light: 'base', dark: 'base'}, options: mermaidOptions(theme.palette.modes.dark)},
    announcementBar: {
      backgroundColor: 'var(--lsf-raised)',
      textColor: 'var(--lsf-text)',
      id: 'development-foundation',
      content: 'LSF alpha documentation. Check each guide’s version and verification scope before following it.',
      isCloseable: false,
    },
    navbar: {
      title: 'LSF',
      items: [
        {type: 'docSidebar', sidebarId: 'start', label: 'Start', position: 'left'},
        {type: 'docSidebar', sidebarId: 'learn', label: 'Learn', position: 'left'},
        {type: 'docSidebar', sidebarId: 'howTo', label: 'How-to', position: 'left'},
        {type: 'docSidebar', sidebarId: 'reference', label: 'Reference', position: 'left'},
        {type: 'docSidebar', sidebarId: 'understand', label: 'Understand', position: 'left'},
        {type: 'docSidebar', sidebarId: 'contribute', label: 'Contribute', position: 'left'},
        {to: '/decisions/', label: 'Decisions', position: 'right'},
        {type: 'docsVersionDropdown', position: 'right', dropdownActiveClassDisabled: true},
        {type: 'search', position: 'right'},
      ],
    },
    footer: {style: 'dark', links: [{title: 'Provenance', items: [
      {label: 'Exact source revision', href: `${repositoryUrl}/tree/${prepared.index.revision}`},
      {label: 'Finite documentation gate', href: `${repositoryUrl}/issues/345`},
    ]}]},
    prism: {theme: prismTheme(theme.palette.modes.light), darkTheme: prismTheme(theme.palette.modes.dark), additionalLanguages: ['bash', 'c', 'csharp', 'go', 'java', 'json', 'powershell', 'protobuf', 'rust', 'toml', 'typescript', 'yaml']},
  } satisfies ThemeConfig,
};

export default config;
