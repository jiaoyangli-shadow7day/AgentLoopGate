/** Fail-open, bounded observer over DeepSeek Harness' public Session events. */

import { createHash } from 'node:crypto'
import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import type { Session, SessionEvent } from '@deepseek-ai/dsh-session'
import type {
  BridgeActor,
  EventBatchRequest,
  EventInput,
  JsonRecord,
  ObserverStatus,
} from './protocol.js'
import './service.js'
import '@deepseek-ai/dsh-session'

export const name = 'agentloopgate-observer'
export const inject = ['agentLoopGate', 'sessions']

export interface Config {
  live: boolean
  backfillOnStart: boolean
  ingestMode: 'reference' | 'mirror'
  persistenceKind: 'jsonl' | 'sqlite' | 'memory' | 'unknown'
  maxBatchEvents: number
  maxBufferEvents: number
  sourceRevision: string
}

export const Config: z<Config> = z.object({
  live: z.boolean().default(true),
  backfillOnStart: z.boolean().default(true),
  ingestMode: z.union(['reference', 'mirror']).default('reference'),
  persistenceKind: z.union(['jsonl', 'sqlite', 'memory', 'unknown']).default('jsonl'),
  maxBatchEvents: z.number().min(1).max(100).default(100),
  maxBufferEvents: z.number().min(1).default(1_000),
  sourceRevision: z.string().required(),
})

interface SessionState {
  readonly sessionId: string
  session: Session
  readonly seen: Set<number>
  readonly pending: Set<number>
  readonly buffer: EventInput[]
  queuedEvents: number
  lossPending: boolean
  chain: Promise<void>
}

class SessionObserver {
  private readonly states = new Map<string, SessionState>()
  private acceptedEvents = 0
  private droppedEvents = 0
  private errorCount = 0
  private lastSourceTraceId: string | undefined
  private disposing = false

  constructor(
    private readonly ctx: Context,
    private readonly config: Config,
  ) {
    if (config.maxBufferEvents < config.maxBatchEvents) {
      throw new Error('agentloopgate-observer: maxBufferEvents must cover one complete batch')
    }
    this.publishStatus()
  }

  backfill(session: Session): void {
    for (const event of session.events) this.observe(session, event)
  }

  observe(session: Session, event: SessionEvent): void {
    if (this.disposing) return
    const state = this.stateFor(session)
    if (state.seen.has(event.seq) || state.pending.has(event.seq)) return
    if (state.queuedEvents >= this.config.maxBufferEvents) {
      this.droppedEvents += 1
      state.lossPending = true
      this.publishStatus()
      return
    }
    state.pending.add(event.seq)
    state.buffer.push(mapEvent(event, this.config.ingestMode))
    state.queuedEvents += 1
    if (state.buffer.length >= this.config.maxBatchEvents) this.scheduleDrain(state, false)
  }

  flush(session: Session): Promise<void> {
    const state = this.stateFor(session)
    return this.scheduleDrain(state, true)
  }

  async dispose(): Promise<void> {
    this.disposing = true
    for (const state of this.states.values()) this.scheduleDrain(state, true)
    await Promise.allSettled([...this.states.values()].map(state => state.chain))
  }

  private stateFor(session: Session): SessionState {
    const sessionId = String(session.id)
    let state = this.states.get(sessionId)
    if (state === undefined) {
      state = {
        sessionId,
        session,
        seen: new Set(),
        pending: new Set(),
        buffer: [],
        queuedEvents: 0,
        lossPending: false,
        chain: Promise.resolve(),
      }
      this.states.set(sessionId, state)
      this.publishStatus()
    } else {
      state.session = session
    }
    return state
  }

  private scheduleDrain(state: SessionState, syncAfter: boolean): Promise<void> {
    const batches: EventInput[][] = []
    while (state.buffer.length > 0) {
      batches.push(state.buffer.splice(0, this.config.maxBatchEvents))
    }
    if (batches.length === 0 && !syncAfter) return state.chain
    state.chain = state.chain.then(async () => {
      for (const events of batches) await this.tryIngest(state, events)
      if (syncAfter) {
        await this.reconcile(state)
        const canonicalEvents = state.session.events
        const canonicalComplete = canonicalEvents.length > 0
          && canonicalEvents.every(event => state.seen.has(event.seq))
        if (canonicalComplete) await this.sync(state)
        else {
          state.lossPending = true
          this.publishStatus()
        }
      }
    }).catch((_observerFailure: unknown) => {
      this.errorCount += 1
      state.lossPending = true
      this.publishStatus()
    })
    return state.chain
  }

  private async tryIngest(state: SessionState, events: EventInput[]): Promise<void> {
    try {
      await this.ingest(state, events)
    } catch (_observerFailure: unknown) {
      this.errorCount += 1
      state.lossPending = true
      this.publishStatus()
    }
  }

  private async ingest(state: SessionState, events: EventInput[]): Promise<void> {
    const batchId = batchIdentifier(state.sessionId, events)
    const actor = actorFor(state.sessionId)
    const request: EventBatchRequest = {
      batch_id: batchId,
      session_id: state.sessionId,
      persistence_kind: this.config.persistenceKind,
      ingest_mode: this.config.ingestMode,
      events,
    }
    try {
      await this.ctx.agentLoopGate.ingestEvents(request, actor)
      for (const event of events) state.seen.add(event.seq)
      this.acceptedEvents += events.length
      this.publishStatus()
    } finally {
      for (const event of events) state.pending.delete(event.seq)
      state.queuedEvents -= events.length
    }
  }

  private async reconcile(state: SessionState): Promise<void> {
    let batch: EventInput[] = []
    for (const event of state.session.events) {
      if (state.seen.has(event.seq) || state.pending.has(event.seq)) continue
      state.pending.add(event.seq)
      state.queuedEvents += 1
      batch.push(mapEvent(event, this.config.ingestMode))
      if (batch.length === this.config.maxBatchEvents) {
        await this.tryIngest(state, batch)
        batch = []
      }
    }
    if (batch.length > 0) await this.tryIngest(state, batch)
  }

  private async sync(state: SessionState): Promise<void> {
    const result = await this.ctx.agentLoopGate.syncTrace({
      session_id: state.sessionId,
      source_revision: this.config.sourceRevision,
      persistence_kind: this.config.persistenceKind,
      ingest_mode: this.config.ingestMode,
    }, actorFor(state.sessionId))
    const sourceTraceId = result['source_trace_id']
    if (typeof sourceTraceId === 'string') this.lastSourceTraceId = sourceTraceId
    state.lossPending = result['evidence_status'] !== 'verified'
    this.publishStatus()
  }

  private publishStatus(): void {
    const status: ObserverStatus = {
      state: [...this.states.values()].some(state => state.lossPending)
        ? 'evidence_incomplete'
        : 'observing',
      acceptedEvents: this.acceptedEvents,
      droppedEvents: this.droppedEvents,
      errorCount: this.errorCount,
      trackedSessions: this.states.size,
      ...(this.lastSourceTraceId === undefined
        ? {}
        : { lastSourceTraceId: this.lastSourceTraceId }),
    }
    this.ctx.agentLoopGate.updateObserverStatus(status)
  }
}

export function apply(ctx: Context, config: Config): void {
  const observer = new SessionObserver(ctx, config)
  if (config.live) {
    ctx.on('session/created', session => { observer.backfill(session) })
    ctx.on('session/event', (session, event) => { observer.observe(session, event) })
    ctx.on('session/flush', session => observer.flush(session))
    ctx.on('session/disposed', session => { void observer.flush(session) })
  }
  if (config.backfillOnStart) {
    for (const session of ctx.sessions.list()) observer.backfill(session)
  }
  ctx.effect(() => async () => { await observer.dispose() }, 'AgentLoopGate observer teardown')
}

function mapEvent(event: SessionEvent, mode: Config['ingestMode']): EventInput {
  const data = mode === 'mirror'
    ? jsonRecord(event.data)
    : { event_digest: sha256(JSON.stringify(event)) }
  return {
    seq: event.seq,
    timestamp: new Date(event.time).toISOString(),
    event_type: event.type,
    data,
  }
}

function jsonRecord(value: unknown): JsonRecord {
  const detached: unknown = JSON.parse(JSON.stringify(value))
  if (detached === null || typeof detached !== 'object' || Array.isArray(detached)) {
    return { value_digest: sha256(JSON.stringify(detached)) }
  }
  return detached as JsonRecord
}

function actorFor(sessionId: string): BridgeActor {
  return { type: 'dsh_plugin', session_id_hash: `sha256:${sha256(sessionId)}` }
}

function batchIdentifier(sessionId: string, events: EventInput[]): string {
  const identity = JSON.stringify({
    sessionId,
    events: events.map(event => [event.seq, event.event_type, event.data]),
  })
  return `BATCH_${sha256(identity).slice(0, 32)}`
}

function sha256(value: string): string {
  return createHash('sha256').update(value).digest('hex')
}

export default { name, inject, Config, apply }
