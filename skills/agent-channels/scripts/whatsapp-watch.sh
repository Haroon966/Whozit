#!/usr/bin/env bash
# Event-driven WhatsApp owner monitor + Cursor CLI agent bridge.
# ONLY one Baileys client may use this auth dir — disable Cursor WhatsApp MCP while watch runs.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
export PINKY_WA_AUTH_DIR="$DIR"
export PINKY_PROJECT_ROOT="$(cd "$DIR/../.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

if [[ ! -f "$DIR/owner.json" ]]; then
  echo "Missing owner.json." >&2
  exit 1
fi
if [[ ! -f "$DIR/creds.json" ]]; then
  echo "Not paired. Run: bash $DIR/login.sh" >&2
  exit 1
fi
if ! command -v agent >/dev/null 2>&1; then
  echo "Install Cursor CLI: curl https://cursor.com/install -fsS | bash && agent login" >&2
  exit 1
fi

# Warn if another baileys uses same auth (causes disconnect 440)
if pgrep -af "baileys-mcp.*${DIR}" >/dev/null 2>&1; then
  echo "WARN: baileys-mcp already using this auth dir — will fight watch (440)." >&2
  echo "      Cursor Settings → MCP → disable/remove whatsapp, then restart watch." >&2
fi

if [[ ! -d "$DIR/node_modules/@whiskeysockets/baileys" ]]; then
  echo "Installing Baileys (one-time)…"
  [[ -f "$DIR/package.json" ]] || printf '%s\n' '{"name":"pinky-wa-login","private":true,"type":"module"}' >"$DIR/package.json"
  npm install --no-fund --no-audit @whiskeysockets/baileys@6 qrcode-terminal qrcode @hapi/boom
fi

cat >"$DIR/watch.mjs" <<'JS'
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
} from '@whiskeysockets/baileys'
import fs from 'fs'
import path from 'path'
import { spawn } from 'child_process'

process.on('uncaughtException', (e) => {
  console.error('uncaught (kept alive):', e.message || e)
})
process.on('unhandledRejection', (e) => {
  console.error('unhandledRejection (kept alive):', e?.message || e)
})

const authDir = process.env.PINKY_WA_AUTH_DIR
const projectRoot = process.env.PINKY_PROJECT_ROOT || path.resolve(authDir, '../..')
const ownerPath = path.join(authDir, 'owner.json')
const inboxPath = path.join(authDir, 'inbox.jsonl')
const statePath = path.join(authDir, 'watch-state.json')
const agentLog = path.join(authDir, 'agent.log')
const pendingPath = path.join(authDir, 'pending-replies.jsonl')

function loadOwner() {
  return JSON.parse(fs.readFileSync(ownerPath, 'utf8'))
}
function saveOwner(o) {
  fs.writeFileSync(ownerPath, JSON.stringify(o, null, 2) + '\n')
}
function loadSeen() {
  try {
    return new Set(JSON.parse(fs.readFileSync(statePath, 'utf8')).seen || [])
  } catch {
    return new Set()
  }
}
function saveSeen(seen) {
  fs.writeFileSync(statePath, JSON.stringify({ seen: [...seen].slice(-500), updatedAt: new Date().toISOString() }, null, 2))
}
function textFromMessage(msg) {
  const m = msg.message || {}
  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    m.videoMessage?.caption ||
    m.documentMessage?.caption ||
    ''
  )
}
function baseUser(jid) {
  return (jid || '').split('@')[0].split(':')[0]
}
function isFromOwner(remoteJid, owner) {
  if (!remoteJid || remoteJid === 'status@broadcast') return false
  if (owner.jid && remoteJid === owner.jid) return true
  if (owner.lid && remoteJid === owner.lid) return true
  const bu = baseUser(remoteJid)
  if (owner.jid && bu === baseUser(owner.jid)) return true
  if (owner.lid && bu === baseUser(owner.lid)) return true
  const digits = String(owner.phone || '').replace(/\D/g, '').replace(/^0/, '')
  const jidDigits = baseUser(owner.jid || '').replace(/\D/g, '')
  if (digits && bu.includes(digits)) return true
  if (jidDigits && bu === jidDigits) return true
  return false
}

const silent = {
  level: 'silent',
  child() { return this },
  trace() {}, debug() {}, info() {}, warn() {}, error() {}, fatal() {},
}

let owner = loadOwner()
const seen = loadSeen()
let attempts = 0
let sockRef = null
let waOpen = false
let busy = false
const jobQueue = []
const recentText = new Map() // text -> ts — dedupe noisy repeats
const AGENT_TIMEOUT_MS = Number(process.env.PINKY_WA_AGENT_TIMEOUT_MS || 180000)
const DEDUPE_MS = 45000

console.error('Pinky WhatsApp ↔ Cursor CLI')
console.error('Project:', projectRoot)
console.error('Owner:', owner.phone, owner.jid, owner.lid || '')
console.error('Keep open. Disable Cursor MCP "whatsapp" while this runs (same session → 440).')
console.error('Q&A uses ask mode (faster). Writes/fixes use full agent.')
console.error('')

function enqueue(job) {
  const key = (job.text || '').trim().toLowerCase()
  const now = Date.now()
  const prev = recentText.get(key)
  if (key && prev && now - prev < DEDUPE_MS) {
    console.error('DEDUPE skip (same text within', DEDUPE_MS, 'ms)')
    return
  }
  if (key) recentText.set(key, now)
  jobQueue.push(job)
  drainQueue()
}

function wantsWrite(text) {
  return /\b(fix|edit|implement|improve|change|write|commit|refactor|create|delete|patch|pr|pull request|add|remove|update|build|make)\b/i.test(text)
}

async function drainQueue() {
  if (busy) return
  const job = jobQueue.shift()
  if (!job) return
  busy = true
  try {
    await runCursorAgent(job)
  } catch (e) {
    console.error('AGENT_FAIL', e.message || e)
    await queueOrSend(job.replyTo, `Pinky agent error: ${String(e.message || e).slice(0, 200)}`)
  } finally {
    busy = false
    if (jobQueue.length) setImmediate(drainQueue)
  }
}

function runCursorAgent({ text, replyTo, id }) {
  return new Promise((resolve, reject) => {
    const prompt = [
      'You are Pinky talking to the project OWNER over WhatsApp.',
      'Reply ONLY for the phone. Short (few lines). Exact code when needed.',
      'Never mention outbox, MCP, IDE modes, Cursor Settings, or internal tooling.',
      'Never say "switch to Agent mode" — you already run via WhatsApp bridge.',
      'If they ask what exists / tree / status: answer from the repo plainly.',
      'If they ask to improve/change code: do the work when tools allow, then summarize what changed.',
      '',
      `Owner WhatsApp message: ${text}`,
    ].join('\n')

    const write = wantsWrite(text)
    const args = write
      ? ['-p', '--force', '--trust', '--output-format', 'text', prompt]
      : ['-p', '--mode', 'ask', '--trust', '--output-format', 'text', prompt]
    console.error('AGENT_RUN', write ? 'full' : 'ask', text.slice(0, 80))
    fs.appendFileSync(agentLog, `\n--- ${new Date().toISOString()} msg=${id} mode=${write ? 'full' : 'ask'} ---\n${text}\n`)

    const child = spawn('agent', args, {
      cwd: projectRoot,
      env: { ...process.env, PATH: process.env.PATH },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let out = ''
    let err = ''
    let settled = false
    const timer = setTimeout(() => {
      if (settled) return
      console.error('AGENT_TIMEOUT kill after', AGENT_TIMEOUT_MS, 'ms')
      try { child.kill('SIGTERM') } catch { /* */ }
      setTimeout(() => { try { child.kill('SIGKILL') } catch { /* */ } }, 3000)
    }, AGENT_TIMEOUT_MS)

    child.stdout.on('data', (d) => { out += d.toString(); fs.appendFileSync(agentLog, d) })
    child.stderr.on('data', (d) => { err += d.toString(); fs.appendFileSync(agentLog, d) })
    child.on('error', (e) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      reject(e)
    })
    child.on('close', async (code) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      console.error('AGENT_DONE exit', code, 'bytes', out.length)
      const raw = (out || err).trim()
      if (!raw) {
        await queueOrSend(replyTo, `Pinky: agent exited ${code} with no text. Try again or check agent.log.`)
        return resolve()
      }
      const parts = raw.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
      let userFacing = (parts.length ? parts[parts.length - 1] : raw).slice(0, 3500)
      userFacing = userFacing.replace(/^Workspace Trust Required[\s\S]*$/m, '').trim() || userFacing
      try {
        await queueOrSend(replyTo, userFacing)
        console.error('AGENT_REPLIED', userFacing.slice(0, 80))
        resolve()
      } catch (e) {
        reject(e)
      }
    })
  })
}

async function sendNow(jid, text) {
  if (!sockRef || !waOpen) throw new Error('wa not open')
  const chunk = 3500
  for (let i = 0; i < text.length; i += chunk) {
    const piece = text.slice(i, i + chunk)
    await Promise.race([
      sockRef.sendMessage(jid, { text: piece }),
      new Promise((_, rej) => setTimeout(() => rej(new Error('send timeout')), 20000)),
    ])
  }
}

async function queueOrSend(jid, text) {
  try {
    await sendNow(jid, text)
  } catch (e) {
    console.error('send deferred:', e.message || e)
    fs.appendFileSync(pendingPath, JSON.stringify({ jid, text, at: new Date().toISOString() }) + '\n')
  }
}

async function flushPending() {
  if (!fs.existsSync(pendingPath) || !waOpen || !sockRef) return
  const lines = fs.readFileSync(pendingPath, 'utf8').split('\n').filter(Boolean)
  if (!lines.length) return
  fs.writeFileSync(pendingPath, '')
  for (const line of lines) {
    try {
      const { jid, text } = JSON.parse(line)
      await sendNow(jid, text)
      console.error('PENDING_SENT', (text || '').slice(0, 60))
    } catch (e) {
      console.error('pending fail', e.message)
      fs.appendFileSync(pendingPath, line + '\n')
    }
  }
}

const { state, saveCreds } = await useMultiFileAuthState(authDir)
const { version } = await fetchLatestBaileysVersion()

async function connect() {
  attempts++
  const sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: false,
    logger: silent,
    markOnlineOnConnect: false,
  })
  sockRef = sock
  waOpen = false
  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update
    if (qr) console.error('Need re-login: bash login.sh')
    if (connection === 'open') {
      waOpen = true
      console.error('WhatsApp connected. Waiting for owner…')
      attempts = 0
      try { await flushPending() } catch (e) { console.error('flush', e.message) }
    }
    if (connection === 'close') {
      waOpen = false
      sockRef = null
      const code = lastDisconnect?.error?.output?.statusCode
      console.error('Disconnected', code)
      if (code === DisconnectReason.loggedOut) {
        console.error('Logged out. Run login.sh')
        process.exit(1)
      }
      // 440 = conflict / replaced — another client stole session (often MCP baileys)
      if (code === 440) {
        console.error('440 conflict: stop other sessions using this WhatsApp (Cursor MCP whatsapp). Retrying…')
      }
      setTimeout(connect, Math.min(15000, 2000 * Math.max(1, attempts)))
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    for (const msg of messages) {
      try {
        if (!msg.message || msg.key.fromMe) continue
        const remote = msg.key.remoteJid
        const text = textFromMessage(msg)
        console.error('INBOUND', remote, (text || '(non-text)').slice(0, 80))
        if (!isFromOwner(remote, owner)) continue
        if (remote.endsWith('@lid') && remote !== owner.lid) {
          owner.lid = remote
          saveOwner(owner)
        }
        const id = msg.key.id
        if (!id || seen.has(id)) continue
        seen.add(id)
        saveSeen(seen)
        fs.appendFileSync(inboxPath, JSON.stringify({
          id, from: remote, text, ts: Number(msg.messageTimestamp) || Date.now(),
          type: type || 'notify', receivedAt: new Date().toISOString(),
        }) + '\n')
        console.error('OWNER_MSG', (text || '').slice(0, 120))
        if (!text.trim()) {
          await queueOrSend(remote, 'Send a text message (media not handled yet).')
          continue
        }
        enqueue({ text, replyTo: remote, id })
      } catch (e) {
        console.error('msg handler error', e.message || e)
      }
    }
  })
}

await connect()
JS

exec node "$DIR/watch.mjs"
