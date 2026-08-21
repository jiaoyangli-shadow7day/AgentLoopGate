import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { SessionId, type SessionEvent } from '@deepseek-ai/dsh-session'
import JsonlSessionPersistence from '@deepseek-ai/dsh-session-persistence-jsonl'
import SqliteSessionPersistence from '@deepseek-ai/dsh-session-persistence-sqlite'
import OpenTelemetrySessionBackend, {
  SessionTelemetryMode,
} from '@deepseek-ai/dsh-session-telemetry-otel'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AgentLoopGateService } from '../src/service.js'
import type {
  BridgeActor,
  EventBatchRequest,
  JsonRecord,
  ObserverStatus,
  TraceSyncRequest,
} from '../src/protocol.js'
import * as observerPlugin from '../src/observer.js'

class FixtureGate extends AgentLoopGateService {
  batches: EventBatchRequest[] = []

  async health(): Promise<JsonRecord> { return { core: 'ready' } }
  async validateContract(): Promise<JsonRecord> { return { valid: true } }
  async checkCandidate(candidateId: string): Promise<JsonRecord> {
    return { candidate_id: candidateId }
  }
  async explainDecision(decisionId: string): Promise<JsonRecord> {
    return { decision_id: decisionId }
  }
  async ingestEvents(request: EventBatchRequest, _actor?: BridgeActor): Promise<JsonRecord> {
    this.batches.push(request)
    return { accepted: request.events.length }
  }
  async syncTrace(_request: TraceSyncRequest, _actor?: BridgeActor): Promise<JsonRecord> {
    return { source_trace_id: 'DSH_NATIVE', evidence_status: 'verified' }
  }
  updateObserverStatus(_status: ObserverStatus): void {}
}

const roots: string[] = []
const contexts: Context[] = []

afterEach(async () => {
  vi.restoreAllMocks()
  await Promise.all(contexts.splice(0).map(async ctx => { await ctx.fiber.dispose() }))
  await Promise.all(roots.splice(0).map(async root => { await rm(root, { recursive: true }) }))
})

type Backend = 'jsonl' | 'sqlite'

async function run(backend: Backend, withObserver: boolean) {
  const root = await mkdtemp(join(tmpdir(), `agentloopgate-${backend}-`))
  roots.push(root)
  const ctx = new Context()
  contexts.push(ctx)
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
    shutdownTimeoutMillis: 200,
    exporter: {
      url: 'http://127.0.0.1:9/v1/logs',
      timeoutMillis: 50,
    },
    processor: {
      scheduledDelayMillis: 10_000,
      maxQueueSize: 32,
      maxExportBatchSize: 32,
      exportTimeoutMillis: 50,
    },
  })
  // Context#get deliberately returns a fresh traceable proxy. Compare the
  // registered implementation record so this test detects replacement rather
  // than proxy identity churn.
  const nativeTelemetry = ctx.reflect._getImpl('sessionTelemetry')?.value
  if (withObserver) {
    await ctx.plugin(FixtureGate)
    await ctx.plugin(observerPlugin, {
      live: true,
      backfillOnStart: true,
      ingestMode: 'reference',
      persistenceKind: backend,
      maxBatchEvents: 2,
      maxBufferEvents: 10,
      sourceRevision: 'deepseek-harness@fixture',
    })
  }
  expect(ctx.reflect._getImpl('sessionTelemetry')?.value).toBe(nativeTelemetry)
  expect(ctx.get('sessionTelemetry')?.sharing).toBe('full')

  const session = ctx.sessions.create(SessionId(`native-${backend}`), {
    meta: { cwd: root },
  })
  session.append('turn/start', { turn: 1 })
  session.append('turn/end', { turn: 1, reason: { kind: 'completed' } })
  await ctx.sessions.flush(session)
  await new Promise(resolve => setTimeout(resolve, 30))
  const persisted = await ctx.sessionPersistence.load(session.id)
  return {
    events: persisted.events.map(logicalEvent),
    observed: withObserver ? (ctx.agentLoopGate as FixtureGate).batches.length : 0,
  }
}

function logicalEvent(event: SessionEvent): object {
  const { time: _time, ...logical } = event
  return logical
}

describe.each(['jsonl', 'sqlite'] as const)('%s native coexistence', backend => {
  it('preserves logical persistence and the enabled OTel provider', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_787_175_600_000)
    const withoutPlugin = await run(backend, false)
    const withPlugin = await run(backend, true)

    expect(withPlugin.events).toEqual(withoutPlugin.events)
    expect(withPlugin.observed).toBeGreaterThan(0)
  })
})
