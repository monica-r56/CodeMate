/* eslint-disable @typescript-eslint/no-var-requires */
const path = require('path');
const esbuild = require('esbuild');

async function main() {
  const extensionRoot = path.join(__dirname, '..');
  const entry = path.join(extensionRoot, 'src', 'webview', 'vapi-browser.ts');
  const outFile = path.join(extensionRoot, 'media', 'vapi.js');

  await esbuild.build({
    entryPoints: [entry],
    bundle: true,
    platform: 'browser',
    format: 'iife',
    outfile: outFile,
    target: ['es2019'],
    define: {
      'process.env.NODE_ENV': '"production"'
    },
    logLevel: 'info'
  });
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error(err);
  process.exit(1);
});

