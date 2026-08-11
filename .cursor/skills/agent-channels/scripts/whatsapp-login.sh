#!/usr/bin/env bash
# One-time WhatsApp QR login into this directory (same auth-dir as MCP).
# USER must run this in THEIR terminal so the QR is visible. Agents must NOT run this.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
export PINKY_WA_AUTH_DIR="$DIR"

if [[ ! -f "$DIR/package.json" ]]; then
  cat >"$DIR/package.json" <<'EOF'
{"name":"pinky-wa-login","private":true,"type":"module"}
EOF
fi

if [[ ! -d "$DIR/node_modules/@whiskeysockets/baileys" ]]; then
  echo "Installing Baileys (one-time)…"
  npm install --no-fund --no-audit @whiskeysockets/baileys@6 qrcode-terminal qrcode @hapi/boom
fi

cat >"$DIR/login.mjs" <<'JS'
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
} from '@whiskeysockets/baileys'
import qrcode from 'qrcode-terminal'
import QRCode from 'qrcode'
import path from 'path'

const authDir = process.env.PINKY_WA_AUTH_DIR
if (!authDir) {
  console.error('PINKY_WA_AUTH_DIR missing')
  process.exit(1)
}

const { state, saveCreds } = await useMultiFileAuthState(authDir)
const { version } = await fetchLatestBaileysVersion()

const silent = {
  level: 'silent',
  child() { return this },
  trace() {}, debug() {}, info() {}, warn() {}, error() {}, fatal() {},
}

let attempts = 0
const maxAttempts = 4

console.error('Pinky WhatsApp login')
console.error('Auth dir:', authDir)
console.error('Phone: WhatsApp → Linked Devices → Link a device')
console.error('Scan the QR below. Agent chat will not show this QR — use this terminal.')
console.error('')

async function connect() {
  attempts++
  const sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: false,
    logger: silent,
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update
    if (qr) {
      qrcode.generate(qr, { small: true })
      try {
        await QRCode.toFile(path.join(authDir, 'qr.png'), qr, { width: 400, margin: 2 })
        console.error('\nAlso wrote: ' + path.join(authDir, 'qr.png'))
        console.error('Open that image if terminal QR is hard to read.\n')
      } catch (e) {
        console.error('qr.png write failed:', e.message)
      }
    }
    if (connection === 'open') {
      console.error('\nOK — paired as', sock.user?.id)
      console.error('Session saved under .pinky/whatsapp/')
      console.error('Tell the agent: paired OK. Then reload Cursor MCP if needed.')
      process.exit(0)
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode
      console.error('Connection closed. statusCode=', code, 'attempt', attempts)
      // 515 = restart required right after pair — retry with saved creds
      if (code !== DisconnectReason.loggedOut && attempts < maxAttempts) {
        setTimeout(connect, 1500)
        return
      }
      process.exit(1)
    }
  })
}

await connect()

setTimeout(() => {
  console.error('Timeout (3 min). Re-run: bash .pinky/whatsapp/login.sh')
  process.exit(1)
}, 180000)
JS

chmod +x "$DIR/login.sh"
exec node "$DIR/login.mjs"
