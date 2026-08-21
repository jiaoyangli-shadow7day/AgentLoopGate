/** Shared protocol values consumed by the service, observer, and tools. */

import type { JsonRecord } from './generated/bridge.js'

export type {
  BridgeActor,
  BridgeError,
  BridgeRequest,
  BridgeResponse,
  JsonRecord,
  JsonScalar,
  JsonValue,
} from './generated/bridge.js'

export interface ObserverStatus {
  state: 'idle' | 'observing' | 'evidence_incomplete' | 'unavailable'
  acceptedEvents: number
  droppedEvents: number
  errorCount: number
  trackedSessions: number
  lastSourceTraceId?: string
}

export interface EventInput {
  seq: number
  timestamp: string
  event_type: string
  data: JsonRecord
}

export interface EventBatchRequest {
  batch_id: string
  session_id: string
  persistence_kind: 'jsonl' | 'sqlite' | 'memory' | 'unknown'
  ingest_mode: 'reference' | 'mirror'
  events: EventInput[]
}

export interface TraceSyncRequest {
  session_id: string
  source_revision: string
  persistence_kind: EventBatchRequest['persistence_kind']
  ingest_mode: EventBatchRequest['ingest_mode']
}
