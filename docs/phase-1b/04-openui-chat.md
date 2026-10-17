# 1b-UI OpenUI chat interface for Ask, with fixed answer cards

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `7008a5a0-ff93-4ff2-af34-71ff3395d117`. Task status: **in progress**. Earlier progress entries are historical; later dated entries record updates.

Replace the Ask screen with a chat built on OpenUI (github.com/thesysdev/openui, MIT). Each question shows three fixed cards built by our code: Without learning, Trained, Search.

## Scope
The web UI only (`web/` plus its build), with static export to the existing S3 + CloudFront hosting. The UI calls the existing API: login, Ask jobs and polling, Warm up, model and snapshot info. Do not change API contracts, Terraform resources beyond what static hosting of the build needs, or other screens' behavior (Sources, Review, Results stay; restyle them only if cheap).
- Allowed: OpenUI's MIT packages (chat shell, components, optionally Chart for Results).
- Not allowed: copying code from thesysdev/open-intelligent-ui, which has no license (use it only as visual reference); OpenUI Cloud or THESYS_API_KEY; any LLM generating the layout or rewriting answers.
- This replaces the earlier "plain HTML + JavaScript, no build step" decision for the web UI. The build must run inside `make deploy`, not as a laptop-only step.

## Inputs
Spec decision "Chat UI"; the web task fffe5129-b6ff-471d-b49d-d77af31fdc34 and its API contract; pack/demo-scenarios.json for starter prompts (medical ones after 1b-2).

## Definition of Done
- The chat thread shows the user's question and, per mode, a card with: the answer text verbatim from the API; status (warming, answering, done, error, timed out); the model version and snapshot id; for Search, its citations with document names; for Trained, a "learned, not a citation" note on any source label.
- The Warm up control and 15-minute readiness state are visible.
- Six starter prompts from the demo pack.
- Shared-password login still gates everything; no secrets in the bundle.
- Works on desktop Chrome at 1440 px and 1280 px wide, readable on a projector (large type).
- Unit tests for the card rendering and polling; existing `make test && make lint` pass; screenshots from a local static build against a fake API are attached to the task.

## Verification
`make test && make lint`; the web build command; screenshots of an empty thread, a warming state, three completed cards and an error card.

Started implementation. Preserving the existing Sources/Review/Results screens and auth API while replacing Ask with an OpenUI React chat mount. Will add locked static build, fixed answer cards, bounded cancellable polling and offline browser proof. Ownership: web/, web build wiring, and static asset upload path only. No live AWS/Box calls.
