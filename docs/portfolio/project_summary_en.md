# Project Summary / EN — Version 2.0 Interim

[README](../../README_EN.md) · [Architecture](architecture.md)

## One line

A social analytics decision dashboard from CSV and X Live to market/competitor gaps and evidence-backed AI history comparison.

## Short summary

Built seven screens with FastAPI, PostgreSQL and Next.js, JA/EN UI, X OAuth/refresh/manual and scheduled sync, and saved AI evidence with History/Compare. Instagram is Deferred: OAuth / Profile foundation only. This is an individual portfolio project, not a customer deployment or production-operation record.

## Detail and implementation scope

CSV / X Provider → common normalization → transactionally committed posts, latest metrics, matching and Trends → shared analytics → aggregate AI evidence. Immutable Demo/Live Project modes prevent fallback. NULL and actual zero remain distinct. UTC rolling cohorts use fixed score weights; Gap combines market score and own coverage.

At-least-once jobs use idempotency and checkpoints; PostgreSQL schedule rows drive a fixed Beat tick and Celery / Redis workers. Provider capabilities gate direct sync and scheduling. Tokens are encrypted in runtime storage outside DB/frontend/job payloads. AI aggregates are read in one snapshot; the connection closes before external waiting. Each generation appends a snapshot; reads and previous comparison make no external call.

Scope: requirements/contracts, DB/schema, API/services/repositories, UI/charts, provider/security boundaries, background jobs, automated tests, Docker, fictional Demo and portfolio documentation.

## Stack

| Area | Technology |
| --- | --- |
| UI | Next.js / React / TypeScript / Tailwind CSS / Recharts |
| API | Python / FastAPI / SQLAlchemy / Pydantic |
| Storage | PostgreSQL / Alembic |
| Jobs | Celery / Redis / fixed Celery Beat tick |
| Provider security | OAuth / PKCE / encrypted runtime SecretStore |
| AI | OpenAI Responses API / Structured Outputs |
| Delivery / test | Docker Compose / pytest / Node built-in test |

## Quality / Performance

Backend **1631 passed / 0 failed / 0 skipped**, **351.52 s** (controlled run ≤600 s). Frontend **84 passed / 0 failed / 0 skipped / 0 cancelled**, 13,753.04691 ms. Typecheck / production build PASS; 19 static routes. OpenAPI **47 paths**; Alembic **0005_v2_provider_core**, five migrations unchanged. Real X / Instagram / OpenAI **0 / 0 / 0**. Local controlled Phase12 warm measurements: Overview ~142 ms, Gap ~43 ms, Trend ranking ~33 ms, Competitor ~131 ms, Trend rebuild ~1.57 s. No production SLA. [Final verification report](../implementation_reports/v2_phase14_portfolio_finish_interim_release_candidate.md).

## Live status / limitations

X Complete / previously real-verified in private environment. Instagram Deferred / OAuth and Profile foundation only.

Instagram posts, metrics, media, insights, pagination and initial/incremental sync remain Deferred. Multi-user authentication, cloud production deployment, SLA and 24/7 operational proof are outside this release. Phase14 makes no real X, Instagram or OpenAI calls; X was previously real-verified. Demo AI is a fixed Fake fixture, not a real model quality evaluation. Stored posts and AI content are not translated. OWN import retains a per-post SELECT for preserved matching. Local benchmark timings are not a production SLA. Full screen-reader audio testing is unperformed.
