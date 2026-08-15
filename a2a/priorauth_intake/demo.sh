#!/usr/bin/env bash
# Send one referral to the intake agent and print the determination.
#
#   ./demo.sh          # the first referral
#   ./demo.sh 3        # the fourth referral
#   ./demo.sh 3 all    # ...and every referral's raw JSON
#
# Runs from a pod inside the cluster, because the intake agent is a ClusterIP
# service. Set TARGET to reach it another way.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

INDEX="${1:-0}"
NAMESPACE="${NAMESPACE:-team2}"
TARGET="${TARGET:-http://priorauth-intake.${NAMESPACE}.svc.cluster.local:8080/}"
DRIVER_POD="${DRIVER_POD:-priorauth-driver}"

NOTE="$(python3 -c "
import json,sys
data = json.load(open('${SCRIPT_DIR}/samples/referrals.json'))['referrals']
print(data[int('${INDEX}')]['note'])
")"

BODY="$(python3 -c "
import json,uuid,sys
note = sys.stdin.read()
print(json.dumps({
    'jsonrpc': '2.0',
    'id': uuid.uuid4().hex,
    'method': 'message/send',
    'params': {'message': {'role': 'user', 'messageId': uuid.uuid4().hex,
                           'parts': [{'kind': 'text', 'text': note}]}},
}))
" <<<"$NOTE")"

if ! kubectl get pod -n "$NAMESPACE" "$DRIVER_POD" >/dev/null 2>&1; then
  echo ">> creating driver pod $DRIVER_POD in $NAMESPACE"
  kubectl run "$DRIVER_POD" -n "$NAMESPACE" --image=curlimages/curl:latest \
    --image-pull-policy=IfNotPresent --restart=Never --command -- sleep infinity >/dev/null
  kubectl wait -n "$NAMESPACE" --for=condition=Ready "pod/$DRIVER_POD" --timeout=90s
fi

echo ">> sending referral $INDEX to $TARGET"
kubectl exec -i -n "$NAMESPACE" "$DRIVER_POD" -- \
  curl -s --max-time 900 -X POST "$TARGET" \
    -H 'Content-Type: application/json' -d "$BODY" \
  | python3 -m json.tool
