/** Versioned Cordis Service Definition for the AgentLoopGate Python Core. */

import { Service, type Context } from '@deepseek-ai/cordis'
import type {
  BridgeActor,
  EventBatchRequest,
  JsonRecord,
  ObserverStatus,
  TraceSyncRequest,
} from './protocol.js'

declare module '@deepseek-ai/cordis' {
  interface Context {
    agentLoopGate: AgentLoopGateService
  }
}

export const SERVICE_VERSION = '1.0' as const

/** Governance service. Privileged promotion and evaluation methods are intentionally absent. */
export abstract class AgentLoopGateService extends Service {
  constructor(ctx: Context) {
    super(ctx, 'agentLoopGate')
  }

  /** Return Core and observer availability without exposing credentials or paths. */
  abstract health(signal?: AbortSignal): Promise<JsonRecord>

  /** Validate the project-owned Objective Contract. */
  abstract validateContract(actor?: BridgeActor, signal?: AbortSignal): Promise<JsonRecord>

  /** Re-run Candidate Check for an already registered candidate. */
  abstract checkCandidate(
    candidateId: string,
    actor?: BridgeActor,
    signal?: AbortSignal,
  ): Promise<JsonRecord>

  /** Return a redacted Decision explanation. */
  abstract explainDecision(
    decisionId: string,
    actor?: BridgeActor,
    signal?: AbortSignal,
  ): Promise<JsonRecord>

  /** Ingest bounded, redacted Session event facts. */
  abstract ingestEvents(
    request: EventBatchRequest,
    actor?: BridgeActor,
    signal?: AbortSignal,
  ): Promise<JsonRecord>

  /** Bind ingested event facts to a SourceTraceRef. */
  abstract syncTrace(
    request: TraceSyncRequest,
    actor?: BridgeActor,
    signal?: AbortSignal,
  ): Promise<JsonRecord>

  /** Publish observer health inside this service only; it never writes the Session log. */
  abstract updateObserverStatus(status: ObserverStatus): void
}
