import type {Config} from '@docusaurus/types';
import type {Options, ThemeConfig} from '@docusaurus/preset-classic';
import path from 'node:path';
import {prepare} from './lib/prepare.mjs';
import {repositoryUrl, websiteRoot} from './lib/repository.mjs';
import {remarkRepositoryLinks, rehypeRepositoryLinks} from './plugins/repository-links.mjs';

const prepared = prepare();
const pluginOptions = {index: prepared.index, assets: prepared.assets, baseUrl: prepared.baseUrl};
const repositoryRemark = () => remarkRepositoryLinks(pluginOptions);
const repositoryRehype = () => rehypeRepositoryLinks(pluginOptions);
const commonDocs = {
  numberPrefixParser: false as const,
  beforeDefaultRemarkPlugins: [repositoryRemark],
  beforeDefaultRehypePlugins: [repositoryRehype],
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
  markdown: {format: 'detect', mermaid: true, hooks: {onBrokenMarkdownLinks: 'throw', onBrokenMarkdownImages: 'throw'}},
  customFields: {contentIdentity: {channel: 'development', revision: prepared.index.revision, dirty: prepared.manifest.dirty}},
  presets: [['classic', {
    docs: {
      ...commonDocs,
      path: '../docs',
      routeBasePath: 'docs',
      exclude: ['wiki/**'],
      sidebarPath: './sidebars.ts',
      editUrl: ({docPath}: {docPath: string}) => `${repositoryUrl}/edit/${prepared.index.revision}/docs/${docPath}`,
    },
    blog: false,
    theme: {customCss: './src/css/foundation.css'},
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
  ],
  themes: ['@docusaurus/theme-mermaid'],
  themeConfig: {
    announcementBar: {
      id: 'development-foundation',
      content: 'Development documentation — not a released snapshot. Foundation only; guide, migration and runtime acceptance remain separate.',
      isCloseable: false,
    },
    navbar: {
      title: 'LSF · development',
      items: [
        {type: 'docSidebar', sidebarId: 'start', label: 'Start', position: 'left'},
        {type: 'docSidebar', sidebarId: 'learn', label: 'Learn', position: 'left'},
        {type: 'docSidebar', sidebarId: 'howTo', label: 'How-to', position: 'left'},
        {type: 'docSidebar', sidebarId: 'reference', label: 'Reference', position: 'left'},
        {type: 'docSidebar', sidebarId: 'understand', label: 'Understand', position: 'left'},
        {type: 'docSidebar', sidebarId: 'contribute', label: 'Contribute', position: 'left'},
        {to: '/decisions/', label: 'Decisions', position: 'right'},
      ],
    },
    footer: {style: 'dark', links: [{title: 'Provenance', items: [
      {label: 'Exact source revision', href: `${repositoryUrl}/tree/${prepared.index.revision}`},
      {label: 'Finite documentation gate', href: `${repositoryUrl}/issues/345`},
    ]}]},
    prism: {additionalLanguages: ['bash', 'c', 'csharp', 'go', 'java', 'json', 'powershell', 'protobuf', 'rust', 'toml', 'typescript', 'yaml']},
  } satisfies ThemeConfig,
};

export default config;
