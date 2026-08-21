/** Local Python Bridge Provider for ctx.agentLoopGate. */

import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import { BridgeClient } from './bridge.js'
import type { BridgeClientConfig } from './bridge.js'
import { AgentLoopGateService, SERVICE_VERSION } from './service.js'
import type {
  BridgeActor,
  EventBatchRequest,
  JsonRecord,
  ObserverStatus,
  TraceSyncRequest,
} from './protocol.js'
import '@deepseek-ai/dsh-subprocess'

export const name = 'agentloopgate-provider'

export interface Config extends BridgeClientConfig {}

export const Config: z<Config> = z.object({
  projectRoot: z.string().required(),
  bridgeCommand: z.string().required(),
  bridgeArgs: z.array(z.string()).default([]),
  requestTimeoutMs: z.number().min(1).default(10_000),
  shutdownGraceMs: z.number().min(1).default(1_000),
  stderrMaxBytes: z.number().min(1).default(65_536),
})

export class AgentLoopGateProvider extends AgentLoopGateService {
  static inject = ['subprocess']
  private readonly client: BridgeClient
  private observer: ObserverStatus = {
    state: 'idle',
    acceptedEvents: 0,
    droppedEvents: 0,
    errorCount: 0,
    trackedSessions: 0,
  }

  constructor(ctx: Context, config: Config) {
    super(ctx)
    this.client = new BridgeClient(ctx.subprocess, config)
    ctx.effect(() => async () => { await this.client.close() }, 'AgentLoopGate bridge teardown')
  }

  async health(signal?: AbortSignal): Promise<JsonRecord> {
    const result = await this.client.call('health', {}, undefined, signal)
    return {
      ...result,
      service_version: SERVICE_VERSION,
      observer: observerRecord(this.observer),
    }
  }

  async validateContract(actor?: BridgeActor, signal?: AbortSignal): Promise<JsonRecord> {
    return await this.client.call('contract.validate', {}, actor, signal)
  }

  async checkCandidate(
    candidateId: string,
    actor?: BridgeActor,
    signal?: AbortSignal,
  ): Promise<JsonRecord> {
    return await this.client.call(
      'candidate.check',
      { candidate_id: candidateId },
      actor,
      signal,
    )
  }

  async explainDecision(
    decisionId: string,
    actor?: BridgeActor,
    signal?: AbortSignal,
  ): Promise<JsonRecord> {
    return await this.client.call(
      'decision.explain',
      { decision_id: decisionId },
      actor,
      signal,
    )
  }

  async ingestEvents(
    request: EventBatchRequest,
    actor?: BridgeActor,
    signal?: AbortSignal,
  ): Promise<JsonRecord> {
    return await this.client.call('events.ingest', eventBatchRecord(request), actor, signal)
  }

  async syncTrace(
    request: TraceSyncRequest,
    actor?: BridgeActor,
    signal?: AbortSignal,
  ): Promise<JsonRecord> {
    return await this.client.call('trace.sync', traceSyncRecord(request), actor, signal)
  }

  updateObserverStatus(status: ObserverStatus): void {
    this.observer = { ...status }
  }
}

function eventBatchRecord(request: EventBatchRequest): JsonRecord {
  return {
    batch_id: request.batch_id,
    session_id: request.session_id,
    persistence_kind: request.persistence_kind,
    ingest_mode: request.ingest_mode,
    events: request.events.map(event => ({ ...event })),
  }
}

function traceSyncRecord(request: TraceSyncRequest): JsonRecord {
  return {
    session_id: request.session_id,
    source_revision: request.source_revision,
    persistence_kind: request.persistence_kind,
    ingest_mode: request.ingest_mode,
  }
}

function observerRecord(status: ObserverStatus): JsonRecord {
  return {
    state: status.state,
    accepted_events: status.acceptedEvents,
    dropped_events: status.droppedEvents,
    error_count: status.errorCount,
    tracked_sessions: status.trackedSessions,
    ...(status.lastSourceTraceId === undefined
      ? {}
      : { last_source_trace_id: status.lastSourceTraceId }),
  }
}

export default AgentLoopGateProvider
