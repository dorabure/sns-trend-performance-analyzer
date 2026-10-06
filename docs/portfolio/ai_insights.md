# AI Insights — Version 2.0 Interim

[README](../../README.md) · [Architecture](architecture.md)

Generate, saved Evidence, History and Compare Previous are implemented. A generation creates one append-only snapshot. History is project-scoped and cursor-paginated. Previous means the preceding snapshot with the same platform and UTC analysis interval; a different interval is not substituted. Legacy / no-previous states remain explicit.

The backend reads aggregate summaries and evidence in a shared read-only transaction, closes its connection before the OpenAI Responses call, validates Structured Outputs / Evidence IDs, then saves content and evidence together. History/detail/compare never call the model. Raw provider responses and credentials are not AI inputs.

Canonical Demo contains one fixed Fake report, so Previous None is expected. Separate disposable Fake history fixtures demonstrate comparison. No OpenAI key is required for saved viewing. Demo screenshots are not proof of real model quality. English UI does not translate a saved Japanese report.

Instagram posts, metrics, media, insights, pagination and initial/incremental sync remain Deferred. Multi-user authentication, cloud production deployment, SLA and 24/7 operational proof are outside this release. Phase14 makes no real X, Instagram or OpenAI calls; X was previously real-verified. Demo AI is a fixed Fake fixture, not a real model quality evaluation. Stored posts and AI content are not translated. OWN import retains a per-post SELECT for preserved matching. Local benchmark timings are not a production SLA. Full screen-reader audio testing is unperformed.
