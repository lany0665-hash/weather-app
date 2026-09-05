#!/usr/bin/env bash
set -euo pipefail

# Deploy firestore.rules using firebase-tools via npx.
# Requires:
# - FIREBASE_PROJECT env var (project ID)
# - FIREBASE_TOKEN env var (CI token from `firebase login:ci`) OR authenticated firebase CLI
# Usage: FIREBASE_PROJECT=your-project-id FIREBASE_TOKEN=xxxx npm run deploy:rules

if [ -z "${FIREBASE_PROJECT:-}" ]; then
  echo "FIREBASE_PROJECT not set. Example: FIREBASE_PROJECT=my-firebase-project"
  exit 1
fi

if [ -z "${FIREBASE_TOKEN:-}" ]; then
  echo "FIREBASE_TOKEN not set. You can create one via 'firebase login:ci' and use it as FIREBASE_TOKEN"
  exit 1
fi

echo "Deploying firestore.rules to project: $FIREBASE_PROJECT"

npx firebase-tools deploy --only firestore:rules --project "$FIREBASE_PROJECT" --token "$FIREBASE_TOKEN"

echo "Done."