# Demo end-to-end test in a real browser

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `5e5b5496-770c-4f26-a03f-0a8ebdd03c63`. Task status: **not started**. Earlier progress entries are historical; later dated entries record updates.

Prove the exact demo Tyson will present works on the deployed stack, clicked through in a real browser, with evidence he can review when he's back.

## Scope
Run after "Deploy, seed and demo runbook" has a live CloudFront URL. Use the **agent-browser** skill (`~/.claude/skills/agent-browser/SKILL.md`) with its own named session or profile; never `close --all`; close only your own session.
Walk the demo runbook in presenting order (pack/demo-scenarios.json), against the live URL:
1. Open the URL, confirm the login page, and check that a wrong password is rejected. Log in with the shared password (read from Secrets Manager at runtime; never print it).
2. **Sources:** the Halvard files are listed; press Sync now and see a sync run appear.
3. **Warm up:** press it and wait until both models are ready (record the cold-start time).
4. **Ask**, for each scenario 1, 2, 4, 5 and 6: submit the question and wait for all three columns (without / with / search). Screenshot each and record the answers, latency and model version, and whether each matches the expected answer.
5. **Scenario 3 (the live change):** make the v2 edit to sable.txt (73 → 96 GB) and the F10 retirement **through the Box API as the service account** (the browser can't sign in to Box as Tyson). Then watch Sources (webhook arrival time) → Review (the changed value and the retirement are flagged) → approve both → switch to the pre-trained v2 → ask the Sable limit and the Quartz location → screenshot. Afterwards, restore v1 so the demo can be repeated.
6. **Results:** the hidden-set scores by question type for the three modes, the hash and the overlap check are shown; screenshot.
7. Security spot checks in the browser: a protected API route without the cookie returns 401; logout works.
Record a short video or GIF of the whole run if the skill supports it.

## Definition of Done
A note "Demo e2e results" with a pass/fail table per step, the timings (cold start, webhook → review, each Ask), embedded screenshots (saved via ws.note.saveAsset), any defects found (each with repro steps), and confirmation that v1 was restored. Defects are reported, not fixed (the coordinator routes fixes).

## Verification
The results note; the screenshots render; the browser session is closed; Box is back to v1.

## Phase 1b update (07:44 UTC)
Test the medical demo: the six medical scenarios from pack/demo-scenarios.json (rewritten in 1b-2), on the new OpenUI Ask chat (task 7008a5a0), against the deployed CloudFront URL. Use your own named agent-browser session; never close others' sessions.
