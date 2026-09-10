import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '../../crm/public/frontend')
const assetsDir = path.join(frontendDir, 'assets')
const src = path.join(frontendDir, 'index.html')
const dest = path.resolve(__dirname, '../../crm/www/crm.html')

// frappe-ui's Vite integration writes hashed entry files beside index.html,
// while its generated HTML references them beneath /assets. Publish those
// entries into the referenced directory before copying the HTML route.
fs.mkdirSync(assetsDir, { recursive: true })
for (const name of fs.readdirSync(frontendDir)) {
  if (!/^index-[^/]+\.(?:js|css|map)$/.test(name)) continue
  fs.renameSync(path.join(frontendDir, name), path.join(assetsDir, name))
}

fs.mkdirSync(path.dirname(dest), { recursive: true })
fs.copyFileSync(src, dest)
