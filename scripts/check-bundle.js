// Does the built page's own script actually PARSE?
//
// vite with minify:false does not evaluate the inline <script> it copies through, so a
// syntax error - a duplicate `const`, a stray backtick - builds green, ships, and only
// shows up as a blank app with one line in a console nobody is reading. That happened:
// `const sf` was declared twice, the whole script died at parse time, and the build,
// the release and the installer were all perfectly happy about it.
//
//   node scripts/check-bundle.js dist-app/index.html
//
// It lives in scripts/, not .build/, because .build/ is gitignored except for the sprite
// atlas - so the first version of this file never reached CI and broke the release the
// moment package.json started calling it. A build guard that is not in the repo is not a
// build guard.
//
// new Function() compiles without running, which is exactly the amount of checking that
// is safe to do to a page that expects a browser.

import fs from 'node:fs'

const files = process.argv.slice(2)
if (!files.length) {
  console.error('usage: node scripts/check-bundle.js <html> [<html>...]')
  process.exit(2)
}

let bad = 0
for (const file of files) {
  if (!fs.existsSync(file)) {
    console.error(`  MISSING  ${file}`)
    bad++
    continue
  }
  const html = fs.readFileSync(file, 'utf8')
  // The app's own code is the big inline block. The others are the JSON payload, the
  // one-liner that stamps the widget flag, and the desktop shell.
  const scripts = [...html.matchAll(/<script(?![^>]*\btype\s*=\s*["'](?:application\/json|text\/plain)["'])[^>]*>([\s\S]*?)<\/script>/g)]
    .map(m => m[1])
    .filter(src => src.trim().length > 200)
  if (!scripts.length) {
    console.error(`  NO SCRIPT  ${file}`)
    bad++
    continue
  }
  let n = 0
  for (const src of scripts) {
    try {
      new Function(src)
      n++
    } catch (e) {
      console.error(`  SYNTAX ERROR in ${file}: ${e.message}`)
      bad++
    }
  }
  if (n === scripts.length) console.log(`  ${file}: ${n} script${n === 1 ? '' : 's'} parse`)
}
process.exit(bad ? 1 : 0)
