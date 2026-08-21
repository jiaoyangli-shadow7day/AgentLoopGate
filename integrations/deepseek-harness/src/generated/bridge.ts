// Generated from AgentLoopGate bridge protocol v1.0. Do not edit.
export type JsonScalar = string | number | boolean | null;
export type JsonValue = JsonScalar | JsonValue[] | { [key: string]: JsonValue };
export type JsonRecord = { [key: string]: JsonValue };

export interface BridgeActor {
  type: "dsh_plugin";
  session_id_hash?: string;
}

export interface BridgeRequest {
  protocol_version: "1.0";
  request_id: string;
  method: string;
  payload: JsonRecord;
  actor?: BridgeActor;
}

export interface BridgeError {
  code: string;
  message: string;
  remediation: string;
}

export interface BridgeResponse {
  protocol_version: "1.0";
  request_id: string;
  ok: boolean;
  result: JsonRecord | null;
  error: BridgeError | null;
}
