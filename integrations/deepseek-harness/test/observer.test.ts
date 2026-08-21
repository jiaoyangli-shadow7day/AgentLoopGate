import { Context } from '@deepseek-ai/cordis'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import { afterEach, describe, expect, it } from 'vitest'
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
  syncs: TraceSyncRequest[] = []
  statuses: ObserverStatus[] = []

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
  async syncTrace(request: TraceSyncRequest, _actor?: BridgeActor): Promise<JsonRecord> {
    this.syncs.push(request)
    return { source_trace_id: 'DSH_FIXTURE', evidence_status: 'verified' }
  }
  updateObserverStatus(status: ObserverStatus): void { this.statuses.push(status) }
}

const contexts: Context[] = []

afterEach(async () => {
  await Promise.all(contexts.splice(0).map(async ctx => { await ctx.fiber.dispose() }))
})

function config(overrides: Partial<observerPlugin.Config> = {}): observerPlugin.Config {
  return {
    live: true,
    backfillOnStart: true,
    ingestMode: 'reference',
    persistenceKind: 'jsonl',
    maxBatchEvents: 2,
    maxBufferEvents: 10,
    sourceRevision: 'deepseek-harness@fixture',
    ...overrides,
  }
}

async function settle(): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, 20))
}

describe('DeepSeek Session observer', () => {
  it('backfills and observes each session sequence once without copying message data', async () => {
    const ctx = new Context()
    contexts.push(ctx)
    await ctx.plugin(SessionStore)
    await ctx.plugin(FixtureGate)
    const session = ctx.sessions.create(SessionId('private-session'), {
      meta: { cwd: process.cwd() },
    })
    session.append('turn/start', { turn: 1 })
    await ctx.plugin(observerPlugin, config({ maxBatchEvents: 1 }))
    session.append('turn/end', { turn: 1, reason: { kind: 'completed' } })
    await ctx.sessions.flush(session)
    await settle()

    const gate = ctx.agentLoopGate as FixtureGate
    const events = gate.batches.flatMap(batch => batch.events)
    expect(events.map(event => event.seq)).toEqual([0, 1])
    expect(events.every(event => Object.keys(event.data).join() === 'event_digest')).toBe(true)
    expect(JSON.stringify(gate.batches)).not.toContain('private-session-data')
    expect(gate.syncs).toHaveLength(1)
    expect(gate.statuses.at(-1)).toMatchObject({
      state: 'observing',
      acceptedEvents: 2,
      droppedEvents: 0,
      lastSourceTraceId: 'DSH_FIXTURE',
    })
  })

  it('marks bounded-buffer loss incomplete while remaining fail open', async () => {
    const ctx = new Context()
    contexts.push(ctx)
    await ctx.plugin(SessionStore)
    await ctx.plugin(FixtureGate)
    await ctx.plugin(observerPlugin, config({
      maxBatchEvents: 2,
      maxBufferEvents: 2,
    }))
    const session = ctx.sessions.create(SessionId('overflow-session'), {
      meta: { cwd: process.cwd() },
    })
    for (let turn = 1; turn <= 5; turn += 1) session.append('turn/start', { turn })
    await settle()

    const status = (ctx.agentLoopGate as FixtureGate).statuses.at(-1)
    expect(status?.state).toBe('evidence_incomplete')
    expect(status?.acceptedEvents).toBeGreaterThan(0)
    expect(status?.droppedEvents).toBeGreaterThan(0)
    expect(status?.errorCount).toBe(0)
  })

  it('reconciles bounded live loss from the canonical Session snapshot on flush', async () => {
    const ctx = new Context()
    contexts.push(ctx)
    await ctx.plugin(SessionStore)
    await ctx.plugin(FixtureGate)
    await ctx.plugin(observerPlugin, config({
      maxBatchEvents: 2,
      maxBufferEvents: 2,
    }))
    const session = ctx.sessions.create(SessionId('recovered-overflow-session'), {
      meta: { cwd: process.cwd() },
    })
    for (let turn = 1; turn <= 5; turn += 1) session.append('turn/start', { turn })

    await ctx.sessions.flush(session)
    await settle()

    const gate = ctx.agentLoopGate as FixtureGate
    const sequence = gate.batches.flatMap(batch => batch.events.map(event => event.seq))
    expect([...new Set(sequence)].sort((left, right) => left - right)).toEqual([0, 1, 2, 3, 4])
    expect(gate.syncs).toHaveLength(1)
    expect(gate.statuses.at(-1)).toMatchObject({
      state: 'observing',
      acceptedEvents: 5,
      droppedEvents: 3,
      errorCount: 0,
    })
  })
})
