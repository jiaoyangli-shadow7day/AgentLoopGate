#!/usr/bin/env bash
set -euo pipefail

VERIFY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERIFY_TMP="$(mktemp -d "${TMPDIR:-/tmp}/agentloopgate-verify.XXXXXX")"

cleanup() {
  rm -rf -- "${VERIFY_TMP}"
}
trap cleanup EXIT

cd "${VERIFY_ROOT}"

echo "[1/6] Python environment and static checks"
uv sync --frozen --reinstall-package agentloopgate
uv run ruff check .
uv run pytest -q

echo "[2/6] Governance fixtures and deterministic public package"
uv run agentloopgate doctor --json
uv run agentloopgate contract validate configs/objective_contract.yaml --json
uv run agentloopgate split verify --json
uv run agentloopgate eval reset-check --fixture tests/fixtures/reset --json
uv run agentloopgate demo --fixture tests/fixtures/public_demo --json
uv run agentloopgate demo \
  --fixture tests/fixtures/public_demo \
  --build-output "${VERIFY_TMP}/public_demo" \
  --project . \
  --json
uv run python -m scripts.verify_public_result_package \
  --package artifacts/research/banking_r15/release
uv run python -m scripts.verify_public_result_package \
  --package artifacts/research/banking_r15/release_v2
uv run python -m scripts.verify_publication_candidate --project .

echo "[3/6] arXiv manuscript evidence binding"
uv run python -m scripts.verify_arxiv_paper --project .

echo "[4/6] Python release artifact clean-room"
uv build --out-dir "${VERIFY_TMP}/python-dist"
VERIFY_SDISTS=("${VERIFY_TMP}"/python-dist/agentloopgate-*.tar.gz)
if [[ ${#VERIFY_SDISTS[@]} -ne 1 || ! -f "${VERIFY_SDISTS[0]}" ]]; then
  echo "Expected exactly one AgentLoopGate source distribution." >&2
  exit 1
fi
if tar -tzf "${VERIFY_SDISTS[0]}" \
  | grep -E '^agentloopgate-[^/]+/(runs|snapshots|candidates|reports)/' \
    >/dev/null; then
  echo "Source distribution contains a root runtime-evidence directory." >&2
  exit 1
fi
uv venv "${VERIFY_TMP}/wheel-venv" --python 3.12
uv pip install \
  --python "${VERIFY_TMP}/wheel-venv/bin/python" \
  "${VERIFY_TMP}"/python-dist/agentloopgate-*.whl
(
  cd "${VERIFY_TMP}"
  "${VERIFY_TMP}/wheel-venv/bin/agentloopgate" --version
  mkdir artifact-project
  "${VERIFY_TMP}/wheel-venv/bin/agentloopgate" init \
    --runtime deepseek-harness \
    --project "${VERIFY_TMP}/artifact-project"
  cd "${VERIFY_TMP}/artifact-project"
  if ARTIFACT_DOCTOR_JSON=$( \
    "${VERIFY_TMP}/wheel-venv/bin/agentloopgate" doctor \
      --runtime deepseek-harness \
      --project . \
      --json
  ); then
    ARTIFACT_DOCTOR_EXIT=0
  else
    ARTIFACT_DOCTOR_EXIT=$?
  fi
  echo "${ARTIFACT_DOCTOR_JSON}"
  ARTIFACT_DOCTOR_JSON="${ARTIFACT_DOCTOR_JSON}" \
  ARTIFACT_DOCTOR_EXIT="${ARTIFACT_DOCTOR_EXIT}" \
    "${VERIFY_TMP}/wheel-venv/bin/python" - <<'PY'
import json
import os

status = int(os.environ["ARTIFACT_DOCTOR_EXIT"])
payload = json.loads(os.environ["ARTIFACT_DOCTOR_JSON"])
if status != 4:
    raise SystemExit(f"fresh-project doctor must exit 4, got {status}")
if payload.get("status") != "not_ready":
    raise SystemExit("fresh-project doctor must report not_ready")
for level in ("observe_ready", "check_ready", "govern_ready"):
    if level not in payload:
        raise SystemExit(f"fresh-project doctor omitted {level}")
PY
)

echo "[5/6] DeepSeek Harness Bundle checks"
cd "${VERIFY_ROOT}/integrations/deepseek-harness"
corepack pnpm install --frozen-lockfile
corepack pnpm run generate:protocol
corepack pnpm run typecheck
corepack pnpm test
corepack pnpm run build
corepack pnpm run test:conformance
corepack pnpm pack --pack-destination "${VERIFY_TMP}"

echo "[6/6] Public-tree Secret/PII check"
cd "${VERIFY_ROOT}"
uv run python scripts/audit_public_tree.py --project "${VERIFY_ROOT}"

echo "AgentLoopGate clean-room checks passed."
echo "Real Banking Pilot and Candidate Ladder are separate credentialed acceptance work."
