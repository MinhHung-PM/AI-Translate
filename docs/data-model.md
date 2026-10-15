# Data model

All primary keys are random UUIDv4 (non-guessable). Every table has `created_at` (and mutable tables
`updated_at`). Enumerations are `VARCHAR` + `CHECK` constraints. Schema source of truth:
`backend/app/models/`, migration `backend/alembic/versions/0001_initial_schema.py`.

```
divisions ─┬─< projects ─┬─< project_memberships >── users ──< user_sessions ──< session_secrets
           │             ├─< glossary_entries          │                          │
           └─< division_assignments >──────────────────┘   ai_provider_configurations ┘
                         └─< meetings ─┬─< meeting_participants
                                       ├─< transcript_imports
                                       ├─< transcript_entries ─< translations
                                       ├─< live_sessions
                                       ├── memos ─┬─< decisions ──┐
                                       │          ├─< action_items ├─< memo_item_sources >── transcript_entries
                                       │          ├─< issues ─────┤
                                       │          └─< risks ──────┘
                                       └─< jobs
usage_records (user, project, meeting, job)      audit_events (actor, project)      oidc_login_states
```

## Key entities

| Table | Notes |
|---|---|
| `users` | Global role: `member`, `project_manager`, `division_manager`, `admin`. `oidc_subject` links an IdP identity. |
| `divisions`, `division_assignments` | A division manager sees summaries of the division's projects; `can_view_transcripts` grants transcript text explicitly. |
| `projects`, `project_memberships` | Access boundary. Membership role `member` or `manager`. `retention_days`, default languages, translation instructions. Soft delete (`deleted_at`). |
| `glossary_entries` | Per project and language pair; unique `(project, src, tgt, source_term)`; `is_active`. |
| `meetings` | Platform (`manual_import`/`teams`/`zoom`/`google_meet`), languages (source nullable = auto), status, soft delete, `content_purged_at`. |
| `transcript_entries` | Normalized utterance: `sequence` (unique per meeting), nullable `speaker_label`/`start_ms`/`end_ms` (never invented), `original_text`, `source_language`, `source_metadata` (JSONB: import format, cue ids, connector, `is_demo`, original wording before a correction). |
| `translations` | Separate from the source; unique `(entry, target_language)`; status `pending/processing/done/failed`, `ambiguity_note`, `is_user_edited` (never overwritten by AI). |
| `memos` | One current memo per meeting. Narrative sections (summary, discussion, open questions, next meeting, PM view) are JSONB validated by Pydantic; workflow status `generating/failed/draft/in_review/approved/rejected`; `prompt_version`, provider, model, generation params; reviewer and timestamp. |
| `decisions`, `action_items`, `issues`, `risks` | Relational rows with `code` (D-1, A-1…), `verification_status` (`draft/needs_review/confirmed/rejected`), `ai_generated`, `confidence`, `owner_text` (as stated) and optional `owner_user_id` (linked by a human), `review_note`. Actions add `due_date`, `due_text` (original wording), `due_needs_confirmation`, `priority`, `status` (`open/in_progress/blocked/done/cancelled`). `project_id` is denormalized for project-scoped queries. |
| `memo_item_sources` | Links an item to supporting transcript entries; CHECK ensures exactly one item FK. The transcript is never duplicated into memos. |
| `ai_provider_configurations` | Per user and provider: model, base URL, default flag, `key_storage` (`none/session/persistent`), AES-GCM ciphertext (persistent only), `key_hint` (last 4 chars). |
| `session_secrets` | Session-only API keys, encrypted, `ON DELETE CASCADE` from `user_sessions`. |
| `user_sessions` | Server-side sessions; only the SHA-256 of the cookie token is stored; per-session CSRF token. |
| `jobs` | Queue + status (`queued/running/succeeded/failed/cancelled`), progress, attempts, error, heartbeat. |
| `usage_records` | Provider, model, tokens (+ whether provider-reported), estimated cost, duration, success, retries, key source. |
| `audit_events` | Actor, action, resource, project, details (IDs/counts only). |

## Indexes

Foreign keys are indexed; additional composite indexes: `meetings(project_id, scheduled_at)`,
`action_items(project_id, status, due_date)`, `usage_records(project_id, created_at)`,
`usage_records(user_id, created_at)`, `glossary(project, src, tgt, is_active)`, `jobs(status, created_at)`,
`audit_events(created_at)`.

## Retention and deletion

* Meeting delete = soft delete (hidden immediately); hard-deleted after 30 days by the worker.
* `projects.retention_days`: transcript entries and translations of older meetings are purged; the
  memo and tracked items remain (their source links disappear with the entries).
* Expired/revoked sessions (and their session-only keys) are purged every 5 minutes.
* Admin can run retention on demand: `POST /api/v1/admin/retention/run`.

## Migrations

```bash
cd backend
alembic upgrade head            # apply
alembic downgrade -1            # roll back one revision (base = drop everything)
alembic revision --autogenerate -m "describe change"   # then review the generated file
alembic check                   # verify models and migrations are in sync (used before release)
```

The test suite runs `downgrade base` → `upgrade head` (`tests/test_integration.py`).
