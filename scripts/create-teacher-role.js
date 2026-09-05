#!/usr/bin/env node
/**
 * create-teacher-role.js
 *
 * Usage: node create-teacher-role.js [teachers.csv] [serviceAccountKey.json]
 * - teachers.csv: CSV with header 'email' or plain list of emails one per line (default: ./teachers.csv)
 * - serviceAccountKey.json: path to Firebase service account JSON (default: ./serviceAccountKey.json)
 *
 * This script will:
 * 1. Initialize Firebase Admin SDK using the provided service account
 * 2. For each email, look up the user UID (create warning if not found)
 * 3. Set document roles/{uid} = { isTeacher: true }
 *
 * NOTE: Run this on a trusted machine (service account has admin privileges).
 */

const fs = require('fs');
const admin = require('firebase-admin');

const teachersPath = process.argv[2] || './teachers.csv';
const svcPath = process.argv[3] || './serviceAccountKey.json';

if (!fs.existsSync(svcPath)) {
  console.error('Service account JSON not found at', svcPath);
  process.exit(1);
}

const raw = fs.readFileSync(teachersPath, 'utf8');
const emails = raw.split(/\r?\n/).map(s => s.trim()).filter(Boolean).filter(line => !line.startsWith('#'));
if (!emails.length) {
  console.error('No teacher emails found in', teachersPath);
  process.exit(1);
}

admin.initializeApp({
  credential: admin.credential.cert(require(svcPath))
});

const db = admin.firestore();

(async () => {
  for (const email of emails) {
    try {
      const user = await admin.auth().getUserByEmail(email);
      const uid = user.uid;
      await db.collection('roles').doc(uid).set({ isTeacher: true });
      console.log(`Granted teacher role to ${email} (uid: ${uid})`);
    } catch (err) {
      console.error(`Failed for ${email}:`, err.message);
    }
  }
  console.log('Done.');
  process.exit(0);
})();
