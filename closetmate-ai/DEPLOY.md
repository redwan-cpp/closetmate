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
| `GCS_BUCKET` | **yes** | The **private** bucket for closet photos (create it in §2). The app refuses to boot in prod without it: without a bucket, photos would sit on the container's disk and vanish on every restart. |
| `TRUSTED_PROXY_HOPS` | yes (Cloud Run: `1`) | How many proxies sit in front of the app. **Verify it** — see §5. |
| `GLOBAL_DAILY_AI_CALLS` | recommended | Hard stop on total AI calls per UTC day (default 20000). Your protection against account-farming bills. |
| `OPENAI_CHAT_MODEL`, `OPENAI_VISION_MODEL`, `OPENAI_VISION_DETAIL`, `GEMINI_MODELS` | optional | Model IDs and image detail. Change here when a provider retires a model. |
| `QUOTA_FREE_{CHAT,VISION,BGREMOVE,INSIGHTS}_MONTHLY` | optional | Free-plan limits (defaults 60 / 40 / 80 / 4). |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | optional | Defaults 3 and 4 per instance. |
| `STUDIO_RMBG_MODEL` | optional | rembg model used for studio-shot cutouts (default `u2netp`, ~4 MB, pre-downloaded in the Dockerfile). A larger model such as `isnet-general-use` cuts cleaner but is ~170 MB: add it to the Dockerfile's `new_session(...)` pre-download line, or the first request on every cold instance will try to fetch it. |
| `MAX_SAVED_LOOKS`, `MAX_WARDROBE_ITEMS`, `CHAT_WARDROBE_LIMIT` | optional | Per-user caps on saved looks (default 200), closet size (500) and how many closet pieces are sent to the stylist prompt (200). |
| `MAX_PHOTOS_PER_USER`, `MAX_PHOTO_BYTES_PER_USER` | optional | Per-user storage caps: number of stored photos (default: closet size + 100) and total bytes (default 250 MB). A user over either gets `403 photos_full`. |
| `PHOTO_URL_TTL_SECONDS` | optional | How long a photo link is valid (default 6 h). A link handed out now stays valid for between half and all of this, because expiry is rounded to half-windows so the app's image cache keeps working. |

`ENV` is detected automatically: Cloud Run sets `K_SERVICE`, which always means production
(docs off, no tracebacks in responses, strict quotas, JSON logs).

## 2. The photo bucket (do this first)

Closet photos are **private**. The database stores an object key; the API hands the app
short-lived signed links, and the app opens them through `GET /files/…` on the API itself. The
bucket is never public and no GCS signed URLs are involved (so no service-account key is needed).

Create a **new** bucket for this. Do not reuse one that ever served public files: an `allUsers`
binding on a bucket exposes every object in it.

```bash
gcloud storage buckets create gs://<project>-closetmate-photos --location us-central1 \
  --uniform-bucket-level-access --public-access-prevention

# A dedicated runtime identity with only what the code needs (create/read/delete/list objects):
gcloud iam service-accounts create closetmate-run
gcloud storage buckets add-iam-policy-binding gs://<project>-closetmate-photos \
  --member serviceAccount:closetmate-run@<project>.iam.gserviceaccount.com \
  --role roles/storage.objectUser
```

Deploy with `--service-account closetmate-run@<project>.iam.gserviceaccount.com` (below), not the
default compute account, which has far broader rights.

Decide two things:

* **Soft delete.** New buckets keep deleted objects recoverable for 7 days by default, so a
  deleted account's photos remain recoverable (to you) for that long. Either turn soft delete off
  for this bucket (`gcloud storage buckets update gs://<bucket> --clear-soft-delete`; confirm the
  flag with `--help` on your gcloud version) or say so in your privacy policy.
* **Request logs.** Cloud Run logs the full request URL, including the `?e=…&s=…` of a photo
  link, so anyone who can read your logs can open a live link for up to `PHOTO_URL_TTL_SECONDS`.
  Treat log access like photo access, or shorten the TTL.

**Clean-up job.** Run `python scripts/cleanup_photos.py --apply` on a schedule (daily is plenty:
Cloud Scheduler → a Cloud Run job using the same image and the same env/secrets). It removes photos
of accounts that no longer exist and photos that were stored but never attached to an item
(older than 24 h). Without `--apply` it only reports.

## 3. Deploy

```bash
gcloud run deploy closetmate-ai \
  --source . --region us-central1 \
  --service-account closetmate-run@<project>.iam.gserviceaccount.com \
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

## 4. Before you launch

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

## 5. Verify `TRUSTED_PROXY_HOPS`

Per-IP rate limits use the Nth-from-the-right entry of `X-Forwarded-For`. Confirm the layout
on your real URL, once:

```bash
curl -s -H 'X-Forwarded-For: 1.2.3.4' https://<service>/health -o /dev/null
```

then look at the request in Cloud Logging / add a temporary log of the header. If the real
client IP is the **last** entry, `1` is right. If you add a load balancer in front, use `2`.
If this is wrong, either every user shares one limiter bucket (too strict) or a caller can
spoof their way around the limits (too loose).

## 6. Known gaps (tracked for the next phases)

* No Alembic yet: schema bootstrap is `CREATE … IF NOT EXISTS` behind a Postgres advisory
  lock. Any column change needs a real migration first.
* Timestamps are ISO-8601 `TEXT`; foreign keys and `ON DELETE CASCADE` are not declared. The
  code keeps deleted accounts out instead (`require_account`), and `scripts/cleanup_photos.py`
  sweeps whatever slips through.
* No email verification or password reset yet. (Account deletion exists: `POST /auth/delete-account`,
  which removes the stored photos first and then the database rows.)
* Deleted photos stay recoverable for the bucket's soft-delete window (see §2).
* The login lockout and rate limits are per instance (in memory); quotas and the global
  daily AI cap are exact (stored in the database).
