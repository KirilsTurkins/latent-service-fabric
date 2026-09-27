export default {
  title: 'Frontend handbook', url: 'https://docs.example',
  baseUrl: process.env.LSF_DOCS_BASE ?? '/', trailingSlash: true,
  onBrokenLinks: 'throw', markdown: {hooks: {onBrokenMarkdownLinks: 'throw'}},
  i18n: {defaultLocale: 'en', locales: ['en', 'de']},
  plugins: [function portableChunkNames() { return {name: 'lsf-portable-chunk-names',
    configureWebpack(_config, isServer) { return isServer ? {} : {optimization: {runtimeChunk: {name: 'runtime-main'}}}; }
  }; }],
  presets: [['classic', {docs: {routeBasePath: '/', sidebarPath: false}, blog: false, theme: {customCss: './style.css'}}]],
  themeConfig: {navbar: {title: 'Frontend handbook', items: [{type: 'localeDropdown', position: 'right'}]},
    colorMode: {defaultMode: 'light', respectPrefersColorScheme: true}}
};
