# Release notes — Version 2.0 Interim

Status: Release Candidate / published as a GitHub public pre-release. Published: Yes. Date: 2026-10-06.

CSV / fictional Canonical Demo and seven JA/EN analysis/settings screens are complete. X OAuth, automatic token refresh, manual and scheduled OWN sync are implemented and previously real-verified in private environment. Scheduled work uses PostgreSQL rows, a fixed Beat tick and Celery / Redis with at-least-once delivery and idempotency. Demo/Live mode isolation and capability gating prevent fallback or unsupported sync. AI Generate, stored evidence, History and Compare Previous are complete. Performance has controlled local validation.

Instagram remains Deferred / OAuth and Profile foundation only.

Backend **1631 passed / 0 failed / 0 skipped**, **351.52 s** (controlled run ≤600 s). Frontend **84 passed / 0 failed / 0 skipped / 0 cancelled**, 13,753.04691 ms. Typecheck / production build PASS; 19 static routes. OpenAPI **47 paths**; Alembic **0005_v2_provider_core**, five migrations unchanged. Real X / Instagram / OpenAI **0 / 0 / 0**. Archive hashes are resolved externally to avoid ZIP self-reference: SNS_Analyzer_V2_Phase14.sha256 and SNS_Analyzer_V2_Interim_ReleaseCandidate.sha256. The RC companion is SNS_Analyzer_V2_Interim_ReleaseCandidate.release_validation.json. [Internal manifest](../release/v2_interim_release_candidate.json).

Instagram posts, metrics, media, insights, pagination and initial/incremental sync remain Deferred. Multi-user authentication, cloud production deployment, SLA and 24/7 operational proof are outside this release. Phase14 makes no real X, Instagram or OpenAI calls; X was previously real-verified. Demo AI is a fixed Fake fixture, not a real model quality evaluation. Stored posts and AI content are not translated. OWN import retains a per-post SELECT for preserved matching. Local benchmark timings are not a production SLA. Full screen-reader audio testing is unperformed.
