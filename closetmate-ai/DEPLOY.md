# Deploying the ClosetMate backend (Cloud Run + Neon)

This is the production checklist the code assumes. Nothing here has been run for you —
these are commands to review and run yourself.

## 1. Secrets and environment

Put secrets in **Secret Manager**, not in the image or `--set-env-vars`.

| Variable | Required | Notes |
|---|---|---|
| `JWT_SECRET` | **yes** | ≥ 32 random chars: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. The app refuses to boot in prod without it. Rotating it signs everyone out (refresh tokens still work, so the app recovers silently). |
| `DATABASE_URL` | **yes** | Neon **pooled** host (the one with `-pooler` in its name). The app refuses to boot in prod on SQLite. |
| `OPENAI_API_KEY` | yes | Primary provider. |
| `GEMINI_API_KEY` | recommended | Fallback provider. |
| `GCS_BUCKET` | yes | Where processed photos are stored. |
| `TRUSTED_PROXY_HOPS` | yes (Cloud Run: `1`) | How many proxies sit in front of the app. **Verify it** — see §4. |
| `GLOBAL_DAILY_AI_CALLS` | recommended | Hard stop on total AI calls per UTC day (default 20000). Your protection against account-farming bills. |
| `OPENAI_CHAT_MODEL`, `OPENAI_VISION_MODEL`, `OPENAI_VISION_DETAIL`, `GEMINI_MODELS` | optional | Model IDs and image detail. Change here when a provider retires a model. |
| `QUOTA_FREE_{CHAT,VISION,BGREMOVE,INSIGHTS}_MONTHLY` | optional | Free-plan limits (defaults 60 / 40 / 80 / 4). |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | optional | Defaults 3 and 4 per instance. |
| `STUDIO_RMBG_MODEL` | optional | rembg model used for studio-shot cutouts (default `u2netp`, ~4 MB, pre-downloaded in the Dockerfile). A larger model such as `isnet-general-use` cuts cleaner but is ~170 MB: add it to the Dockerfile's `new_session(...)` pre-download line, or the first request on every cold instance will try to fetch it. |
| `MAX_SAVED_LOOKS`, `MAX_WARDROBE_ITEMS`, `CHAT_WARDROBE_LIMIT` | optional | Per-user caps on saved looks (default 200), closet size (500) and how many closet pieces are sent to the stylist prompt (200). |

`ENV` is detected automatically: Cloud Run sets `K_SERVICE`, which always means production
(docs off, no tracebacks in responses, strict quotas, JSON logs).

## 2. Deploy

```bash
gcloud run deploy closetmate-ai \
  --source . --region us-central1 \
  --cpu 2 --memory 2Gi --cpu-boost \
  --concurrency 10 --max-instances 10 --min-instances 0 \
  --timeout 60 \
  --set-env-vars ENV=prod,TRUSTED_PROXY_HOPS=1,GCS_BUCKET=<bucket> \
  --set-secrets JWT_SECRET=jwt-secret:latest,DATABASE_URL=database-url:latest,OPENAI_API_KEY=openai-api-key:latest,GEMINI_API_KEY=gemini-api-key:latest
```

Why these numbers:

* **`--max-instances`** is a cost circuit-breaker *and* the database connection budget:
  `max-instances × (DB_POOL_SIZE + DB_MAX_OVERFLOW)` must stay far below Neon's connection
  limit (default `10 × 7 = 70`). Raise both together, never one alone.
* **`--concurrency 10`** — background removal is CPU-bound; 80 concurrent requests on 2 vCPUs
  just makes every request slow.
* **`--cpu-boost`** speeds up cold starts. The background-removal model is baked into the
  image (see `Dockerfile`), so a cold start no longer downloads it.
* **`--min-instances 1`** removes cold starts for a few dollars a month once you have users.

## 3. Before you launch

- [ ] **Budget alerts**: Cloud Billing → Budgets & alerts, at 50 / 90 / 100 % of a monthly cap.
      Also set a monthly spend limit in the OpenAI dashboard.
- [ ] `python scripts/check_models.py --strict` passes (every configured model ID is live).
- [ ] `scripts/pg_smoke.py` passes against a **throw-away** Postgres (a local container or a scratch
      Neon branch, never prod). The pytest suite only ever uses SQLite, so this is what exercises
      the Postgres-only paths: concurrent schema bootstrap, the quota upsert under contention, the
      saved-looks advisory lock and the refresh-token race. See the docstring for the one-liner.
- [ ] After changing `requirements.txt`: rebuild the image and run the suite *inside it*
      (`docker run --rm <image> sh -c "pip install -r requirements-dev.txt && python -m pytest -q"`).
      The pins are the versions that passed that run on Python 3.11; unpinned, every deploy used
      to pick up whatever was newest that day.
- [ ] `GET /ready` returns `{"status":"ready"}` on the deployed URL (database reachable).
- [ ] Neon: confirm point-in-time restore is enabled and how far back it goes on your plan.
- [ ] Do **not** point an uptime monitor at `/ready` every minute — it keeps a scale-to-zero
      database awake around the clock. Monitor `/health` (touches no database).

## 4. Verify `TRUSTED_PROXY_HOPS`

Per-IP rate limits use the Nth-from-the-right entry of `X-Forwarded-For`. Confirm the layout
on your real URL, once:

```bash
curl -s -H 'X-Forwarded-For: 1.2.3.4' https://<service>/health -o /dev/null
```

then look at the request in Cloud Logging / add a temporary log of the header. If the real
client IP is the **last** entry, `1` is right. If you add a load balancer in front, use `2`.
If this is wrong, either every user shares one limiter bucket (too strict) or a caller can
spoof their way around the limits (too loose).

## 5. Known gaps (tracked for the next phases)

* No Alembic yet: schema bootstrap is `CREATE … IF NOT EXISTS` behind a Postgres advisory
  lock. Any column change needs a real migration first.
* Timestamps are ISO-8601 `TEXT`; foreign keys and `ON DELETE CASCADE` are not declared.
* Photos in GCS are made public and are not yet deleted with the item/account.
* No email verification or password reset; no account-deletion endpoint.
* The login lockout and rate limits are per instance (in memory); quotas and the global
  daily AI cap are exact (stored in the database).
