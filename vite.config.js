// One source, two products.
//
//   vite build --mode standalone  ->  ./roadmap.html   (the file friends already have)
//   vite build --mode app         ->  ./dist-app/      (what Tauri bundles)
//
// The only difference is how the two binaries travel. Standalone base64-inlines
// them, because that file has to survive being dragged into a Discord DM. The app
// ships them as real files: bestiary.jpg is 2019x5195 and decodes to ~40 MiB of
// RGBA, and a URL lets WebView2 drop and re-decode it, while a data: URI also
// pins a permanent 2.9 MB string in the DOM. That one choice is most of the
// resident-memory budget.
//
// Data still comes from build-data.py. Vite does not parse a line of RotMG XML;
// it only places what that script already produced.

import { createLogger, defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'
import { copyFileSync, existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const p = (...s) => resolve(here, ...s)

const PAYLOAD = {
  data: p('rotmg-data.json'),
  atlas: p('.build/sprite-atlas.png'),
  bestiary: p('assets/bestiary.jpg'),
  shell: p('src/shell.js'),
  font400: p('assets/fonts/silkscreen-400.woff2'),
  font700: p('assets/fonts/silkscreen-700.woff2'),
}
const ATLAS_FILE = 'sprite-atlas.png'
const BESTIARY_FILE = 'bestiary.jpg'

function must(path) {
  if (!existsSync(path)) {
    throw new Error(`missing build input: ${path}\n  -> run "npm run data" first (build.ps1 step 3)`)
  }
  return path
}

// String.replace() treats the $-escapes in the REPLACEMENT string as patterns, and
// the payload is 2.3 MB of arbitrary JSON plus 3 MB of base64. Always replace with
// a function so the payload lands literally.
const put = (html, token, value) => html.replace(token, () => value)

const dataUri = (mime, path) =>
  `data:${mime};base64,${readFileSync(must(path)).toString('base64')}`

/**
 * Fills the three placeholders build-data.py invented: __ROTMG_DATA__,
 * __SPRITE_ATLAS__, __BESTIARY__. Keeping those exact tokens means src/index.html
 * is still the file build-data.py used to consume, so the Python output and the
 * Vite output can be diffed against each other during the switchover - and they
 * are byte-identical once line endings are normalised.
 */
function rotmgPayload({ inline }) {
  return {
    name: 'rotmg-payload',

    // Emitted here, not in transformIndexHtml: the Rollup asset context is
    // guaranteed in buildStart and is not in Vite's HTML hooks.
    buildStart() {
      if (inline) return
      this.emitFile({ type: 'asset', fileName: ATLAS_FILE, source: readFileSync(must(PAYLOAD.atlas)) })
      this.emitFile({ type: 'asset', fileName: BESTIARY_FILE, source: readFileSync(must(PAYLOAD.bestiary)) })
    },

    // Dev only. Without this, `tauri dev` draws every sprite as a broken box and
    // the bestiary as a 404, which reads like a data bug and is not one.
    configureServer(server) {
      if (inline) return
      const serve = (route, file, type) => (req, res, next) => {
        if (req.url !== route) return next()
        const buf = readFileSync(must(file))
        res.setHeader('Content-Type', type)
        res.setHeader('Content-Length', buf.length)
        res.end(buf)
      }
      server.middlewares.use(serve(`/${ATLAS_FILE}`, PAYLOAD.atlas, 'image/png'))
      server.middlewares.use(serve(`/${BESTIARY_FILE}`, PAYLOAD.bestiary, 'image/jpeg'))
    },

    transformIndexHtml: {
      order: 'pre',
      handler(html) {
        // The same escape build-data.py applies: a bare "</" inside a <script>
        // block ends the block, and item descriptions contain arbitrary text.
        const json = readFileSync(must(PAYLOAD.data), 'utf8').replace(/<\//g, '<\\/')
        html = put(html, '__ROTMG_DATA__', json)

        // The pixel font is inlined in BOTH builds, unlike the atlas and the bestiary.
        // It is 16 KB for the pair, the CSP forbids fetching a font from anywhere, and a
        // headline font that arrives late is worse than one that costs 21 KB of base64.
        html = put(html, '__FONT_PIXEL_400__', dataUri('font/woff2', PAYLOAD.font400))
        html = put(html, '__FONT_PIXEL_700__', dataUri('font/woff2', PAYLOAD.font700))

        if (inline) {
          html = put(html, '__SPRITE_ATLAS__', dataUri('image/png', PAYLOAD.atlas))
          html = put(html, '__BESTIARY__', dataUri('image/jpeg', PAYLOAD.bestiary))
          // No shell.js in the standalone: the pin, the opacity slider and the
          // window commands do not exist in a browser. Leaving it out is what
          // keeps the shipped file identical to the one build-data.py produced.
          return html
        }

        // Root-absolute: Tauri serves frontendDist at the origin root, and the dev
        // middleware above answers the same two routes.
        html = put(html, '__SPRITE_ATLAS__', `/${ATLAS_FILE}`)
        html = put(html, '__BESTIARY__', `/${BESTIARY_FILE}`)

        // Inlined rather than linked: shell.js is a few KB, needs no module graph,
        // and inlining keeps src/index.html free of any tag the standalone build
        // would then have to strip back out.
        const shell = readFileSync(must(PAYLOAD.shell), 'utf8')
        return html.replace('</body>', () => `<script>\n${shell}\n</script>\n</body>`)
      },
    },
  }
}

/** vite build writes src/index.html -> <outDir>/index.html. The shipped name is roadmap.html. */
function nameItRoadmap(outDir) {
  return {
    name: 'rotmg-name-it-roadmap',
    closeBundle() {
      const to = p('roadmap.html')
      copyFileSync(p(outDir, 'index.html'), to)
      console.log(`\n  roadmap.html  ${(statSync(to).size / 1048576).toFixed(2)} MB  (single file, opens anywhere)`)
    },
  }
}

// Vite's CSS resolver sees the atlas url() in the inline <style> and warns that it
// could not resolve it at build time. It is right that it cannot, and wrong that it
// matters: this config replaces the token and emits the file it names. Drop that one
// line so a clean build reads as clean.
function quietUnresolvedAsset() {
  const base = createLogger()
  const noisy = (msg) =>
    typeof msg === 'string' &&
    msg.includes("didn't resolve at build time") &&
    (msg.includes(ATLAS_FILE) || msg.includes(BESTIARY_FILE))
  return {
    ...base,
    warn(msg, opts) { if (!noisy(msg)) base.warn(msg, opts) },
    warnOnce(msg, opts) { if (!noisy(msg)) base.warnOnce(msg, opts) },
  }
}

export default defineConfig(({ mode }) => {
  const standalone = mode === 'standalone'

  return {
    root: p('src'),
    base: './',
    publicDir: false,
    clearScreen: false,
    customLogger: quietUnresolvedAsset(),
    // Tauri exposes TAURI_ENV_* to the frontend build.
    envPrefix: ['VITE_', 'TAURI_ENV_'],

    // Fixed port, no fallback: tauri.conf.json's devUrl points here, and a silent
    // hop to 1421 leaves `tauri dev` staring at a blank window.
    server: { host: '127.0.0.1', port: 1420, strictPort: true },

    plugins: [
      rotmgPayload({ inline: standalone }),
      ...(standalone
        ? [viteSingleFile({ removeViteModuleLoader: true }), nameItRoadmap('dist-standalone')]
        : []),
    ],

    build: {
      outDir: standalone ? p('dist-standalone') : p('dist-app'),
      emptyOutDir: true,
      // The page is one inline <script>; there is nothing to down-level. The app
      // target only ever runs on evergreen WebView2, the standalone on whatever
      // browser a friend happens to have.
      target: standalone ? 'es2020' : 'chrome114',
      // Never silently base64 an asset in the app build - that is the exact cost
      // this target exists to avoid.
      assetsInlineLimit: standalone ? Number.MAX_SAFE_INTEGER : 0,
      // The standalone is unminified today. Keep it that way so a regression shows
      // up in a diff instead of hiding in a mangled blob.
      minify: false,
      cssCodeSplit: false,
      reportCompressedSize: false,
      chunkSizeWarningLimit: 8192,
    },
  }
})
