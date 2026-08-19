#!/usr/bin/env bash
# Send one article to the editor agent and print the front-page brief.
#
#   ./demo.sh          # the first article
#   ./demo.sh 2        # the third article
#
# Runs from a pod inside the cluster, because the editor agent is a ClusterIP
# service. Set TARGET to reach it another way.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

INDEX="${1:-0}"
NAMESPACE="${NAMESPACE:-team2}"
TARGET="${TARGET:-http://newsroom-editor.${NAMESPACE}.svc.cluster.local:8080/}"
DRIVER_POD="${DRIVER_POD:-newsroom-driver}"

ARTICLE="$(python3 -c "
import json,sys
data = json.load(open('${SCRIPT_DIR}/samples/articles.json'))['articles']
print(data[int('${INDEX}')]['article'])
")"

BODY="$(python3 -c "
import json,uuid,sys
article = sys.stdin.read()
print(json.dumps({
    'jsonrpc': '2.0',
    'id': uuid.uuid4().hex,
    'method': 'message/send',
    'params': {'message': {'role': 'user', 'messageId': uuid.uuid4().hex,
                           'parts': [{'kind': 'text', 'text': article}]}},
}))
" <<<"$ARTICLE")"

if ! kubectl get pod -n "$NAMESPACE" "$DRIVER_POD" >/dev/null 2>&1; then
  echo ">> creating driver pod $DRIVER_POD in $NAMESPACE"
  kubectl run "$DRIVER_POD" -n "$NAMESPACE" --image=curlimages/curl:latest \
    --image-pull-policy=IfNotPresent --restart=Never --command -- sleep infinity >/dev/null
  kubectl wait -n "$NAMESPACE" --for=condition=Ready "pod/$DRIVER_POD" --timeout=90s
fi

echo ">> sending article $INDEX to $TARGET"
kubectl exec -i -n "$NAMESPACE" "$DRIVER_POD" -- \
  curl -s --max-time 900 -X POST "$TARGET" \
    -H 'Content-Type: application/json' -d "$BODY" \
  | python3 -m json.tool
