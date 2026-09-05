Param()

# PowerShell script to deploy firestore.rules using firebase-tools
# Requirements:
# - Set environment variable FIREBASE_PROJECT (project id)
# - Set environment variable FIREBASE_TOKEN (CI token from 'firebase login:ci')
# Usage (PowerShell):
# $env:FIREBASE_PROJECT='your-project-id'; $env:FIREBASE_TOKEN='token'; npm run deploy:rules

if (-not $env:FIREBASE_PROJECT) {
  Write-Error "FIREBASE_PROJECT not set. Example: $env:FIREBASE_PROJECT='my-firebase-project'"
  exit 1
}
if (-not $env:FIREBASE_TOKEN) {
  Write-Error "FIREBASE_TOKEN not set. Create one with 'firebase login:ci' and set it as FIREBASE_TOKEN"
  exit 1
}

Write-Host "Deploying firestore.rules to project: $($env:FIREBASE_PROJECT)"

$npx = if (Test-Path "./node_modules/.bin/firebase") { './node_modules/.bin/firebase' } else { 'npx' }
& $npx firebase-tools deploy --only firestore:rules --project $env:FIREBASE_PROJECT --token $env:FIREBASE_TOKEN

Write-Host "Done."