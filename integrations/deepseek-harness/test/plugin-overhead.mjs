import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { performance } from 'node:perf_hooks'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import JsonlSessionPersistence from '@deepseek-ai/dsh-session-persistence-jsonl'
import SqliteSessionPersistence from '@deepseek-ai/dsh-session-persistence-sqlite'
import OpenTelemetrySessionBackend, {
  SessionTelemetryMode,
} from '@deepseek-ai/dsh-session-telemetry-otel'
import { AgentLoopGateService } from '../lib/service.js'
import * as observerPlugin from '../lib/observer.js'

const here = dirname(fileURLToPath(import.meta.url))
const packageRoot = resolve(here, '..')
const projectRoot = resolve(packageRoot, '../..')
const output = resolve(
  process.env.AGENTLOOPGATE_ABLATION_OUTPUT
    ?? process.argv[2]
    ?? join(projectRoot, 'artifacts/research/banking_r2/ablations/plugin_coexistence_overhead.json'),
)
if (relative(projectRoot, output).startsWith('..')) {
  throw new Error('output must remain under the AgentLoopGate project root')
}

class FixtureGate extends AgentLoopGateService {
  batches = []

  async health() { return { core: 'ready' } }
  async validateContract() { return { valid: true } }
  async checkCandidate(candidateId) { return { candidate_id: candidateId } }
  async explainDecision(decisionId) { return { decision_id: decisionId } }
  async ingestEvents(request) {
    this.batches.push(request)
    return { accepted: request.events.length }
  }
  async syncTrace() {
    return { source_trace_id: 'DSH_ABLATION', evidence_status: 'verified' }
  }
  updateObserverStatus() {}
}

const existing = await readExisting(output)
if (existing !== undefined) {
  process.stdout.write(`${JSON.stringify(existing)}\n`)
  process.exit(0)
}

const iterations = 30
const eventCount = 100
const results = {}
for (const backend of ['jsonl', 'sqlite']) {
  const samples = []
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const order = iteration % 2 === 0 ? [false, true] : [true, false]
    const pair = {}
    for (const withObserver of order) {
      pair[withObserver ? 'plugin' : 'baseline'] = await runOnce({
        backend,
        withObserver,
        iteration,
        eventCount,
      })
    }
    if (pair.plugin.eventDigest !== pair.baseline.eventDigest) {
      throw new Error(`${backend} logical Session events changed with the plugin enabled`)
    }
    samples.push({
      baselineMs: pair.baseline.elapsedMs,
      pluginMs: pair.plugin.elapsedMs,
      overheadMs: pair.plugin.elapsedMs - pair.baseline.elapsedMs,
      eventDigest: pair.plugin.eventDigest,
      telemetryPreserved: pair.plugin.telemetryPreserved,
      observedEvents: pair.plugin.observedEvents,
    })
  }
  const overhead = samples.map(sample => sample.overheadMs)
  results[backend] = {
    iterations,
    eventCount,
    sessionEventHashEquivalent: true,
    persistenceSurvival: true,
    otelCoexistence: samples.every(sample => sample.telemetryPreserved),
    observerComplete: samples.every(sample => sample.observedEvents === eventCount),
    p50OverheadMs: percentile(overhead, 0.50),
    p95OverheadMs: percentile(overhead, 0.95),
    samples,
  }
}

const studyPath = resolve(
  process.env.AGENTLOOPGATE_ABLATION_STUDY
    ?? join(projectRoot, 'configs/banking_r2_study.yaml'),
)
if (relative(projectRoot, studyPath).startsWith('..')) {
  throw new Error('study must remain under the AgentLoopGate project root')
}
const studyText = await readFile(studyPath, 'utf8')
const studyDigest = studyText.match(/^study_digest:\s*(sha256:[0-9a-f]{64})$/m)?.[1]
if (studyDigest === undefined) throw new Error('frozen Banking R2 study digest is unavailable')
const protocolDigest = process.env.AGENTLOOPGATE_ABLATION_PROTOCOL_DIGEST
  ?? studyText.match(/^protocol_digest:\s*(sha256:[0-9a-f]{64})$/m)?.[1]
if (protocolDigest === undefined) throw new Error('frozen Banking R2 protocol digest is unavailable')
const payload = {
  schema_version: '1.0',
  ablation_id: 'plugin_coexistence_overhead',
  study_digest: studyDigest,
  protocol_digest: protocolDigest,
  synthetic_control: true,
  formal_decision: false,
  additional_model_calls: false,
  plugin_build_digest: await directoryDigest(join(packageRoot, 'lib')),
  environment: { node: process.version, platform: process.platform, arch: process.arch },
  results,
}
const artifact = { ...payload, artifact_digest: digest(payload) }
await mkdir(dirname(output), { recursive: true })
await writeFile(output, `${canonical(artifact)}\n`, { flag: 'wx' })
process.stdout.write(`${JSON.stringify(artifact)}\n`)

async function runOnce({ backend, withObserver, iteration, eventCount }) {
  const root = await mkdtemp(join(tmpdir(), `agentloopgate-r2-${backend}-`))
  const ctx = new Context()
  try {
    await ctx.plugin(SessionStore)
    if (backend === 'jsonl') {
      await ctx.plugin(JsonlSessionPersistence, {
        root: join(root, 'sessions'),
        compression: 'none',
      })
    } else {
      await ctx.plugin(SqliteSessionPersistence, { path: join(root, 'sessions.db') })
    }
    await ctx.plugin(OpenTelemetrySessionBackend, {
      mode: SessionTelemetryMode.FULL,
      shutdownTimeoutMillis: 50,
      exporter: { url: 'http://127.0.0.1:9/v1/logs', timeoutMillis: 20 },
      processor: {
        scheduledDelayMillis: 10_000,
        maxQueueSize: 256,
        maxExportBatchSize: 256,
        exportTimeoutMillis: 20,
      },
    })
    const nativeTelemetry = ctx.reflect._getImpl('sessionTelemetry')?.value
    if (withObserver) {
      await ctx.plugin(FixtureGate)
      await ctx.plugin(observerPlugin, {
        live: true,
        backfillOnStart: true,
        ingestMode: 'reference',
        persistenceKind: backend,
        maxBatchEvents: 25,
        maxBufferEvents: 200,
        sourceRevision: 'deepseek-harness@0.1.0-rc.8',
      })
    }
    const telemetryPreserved = (
      ctx.reflect._getImpl('sessionTelemetry')?.value === nativeTelemetry
      && ctx.get('sessionTelemetry')?.sharing === 'full'
    )
    const session = ctx.sessions.create(SessionId(`r2-overhead-${backend}-${iteration}`), {
      meta: { cwd: root },
    })
    const started = performance.now()
    for (let index = 0; index < eventCount / 2; index += 1) {
      session.append('turn/start', { turn: index })
      session.append('turn/end', { turn: index, reason: { kind: 'completed' } })
    }
    await ctx.sessions.flush(session)
    if (withObserver) {
      await waitFor(() => observedCount(ctx.agentLoopGate) === eventCount)
    }
    const elapsedMs = performance.now() - started
    const persisted = await ctx.sessionPersistence.load(session.id)
    const logical = persisted.events.map(({ time: _time, ...event }) => event)
    return {
      elapsedMs: rounded(elapsedMs),
      eventDigest: digest(logical),
      telemetryPreserved,
      observedEvents: withObserver ? observedCount(ctx.agentLoopGate) : 0,
    }
  } finally {
    await ctx.fiber.dispose()
    await rm(root, { recursive: true })
  }
}

function observedCount(gate) {
  return gate.batches.reduce((total, batch) => total + batch.events.length, 0)
}

async function waitFor(predicate) {
  const deadline = performance.now() + 2_000
  while (!predicate()) {
    if (performance.now() >= deadline) throw new Error('observer did not ingest every event')
    await new Promise(resolve => setTimeout(resolve, 2))
  }
}

function percentile(values, probability) {
  const ordered = [...values].sort((left, right) => left - right)
  const index = Math.max(0, Math.ceil(probability * ordered.length) - 1)
  return rounded(ordered[index])
}

function rounded(value) {
  return Number(value.toFixed(6))
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function digest(value) {
  return `sha256:${createHash('sha256').update(canonical(value)).digest('hex')}`
}

async function directoryDigest(root) {
  const files = []
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) await visit(path)
      else if (entry.isFile()) files.push(path)
    }
  }
  await visit(root)
  const manifest = {}
  for (const path of files.sort()) {
    manifest[relative(root, path)] = `sha256:${createHash('sha256').update(await readFile(path)).digest('hex')}`
  }
  return digest(manifest)
}

async function readExisting(path) {
  try {
    const parsed = JSON.parse(await readFile(path, 'utf8'))
    const { artifact_digest: expected, ...payload } = parsed
    if (expected !== digest(payload)) throw new Error('existing plugin ablation digest mismatch')
    return parsed
  } catch (error) {
    if (error?.code === 'ENOENT') return undefined
    throw error
  }
}
