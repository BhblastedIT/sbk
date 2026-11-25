# Gmail Pipeline — SBK

## What it does

Downloads all email from your Gmail mailboxes (one browser login each), parses it, enriches it,
and produces a relationship graph for SBK.

## Data architecture

```
~/.sbk-data/
├── emails/                              ← L0: RAW (immutable)
│   ├── accounts.json                    ← OAuth registry per mailbox
│   ├── acme/
│   │   ├── messages.parquet             ← all downloaded email
│   │   ├── chunks/                      ← temp during download
│   │   └── download.log
│   ├── globex/
│   └── ...
│
├── enriched/                            ← L1: ENRICHED (cross-account)
│   ├── contacts.parquet                 ← deduplicated people
│   ├── interactions.parquet             ← who→who graph with frequency
│   └── threads.parquet                  ← reconstructed threads
│
└── exports/                             ← L2: EXPORT for SBK
    ├── network-graph.json               ← top N relationships with score
    └── relationship-scores.parquet      ← score 0-100 per contact
```

### L0 — messages.parquet (per account)

| Column | Type | Description |
|---------|------|-------------|
| id | str | Gmail message ID |
| thread_id | str | Gmail thread ID |
| date | datetime | Send date (UTC) |
| from_addr | str | Sender raw ("Name <email>") |
| to_addr | str | Recipients raw (comma-sep) |
| cc | str | CC raw |
| bcc | str | BCC raw |
| subject | str | Subject |
| body_text | str | Text body (max 50K chars, HTML stripped) |
| labels | str | Gmail labels (comma-sep) |
| message_id | str | RFC822 Message-ID header |
| in_reply_to | str | In-Reply-To header |
| snippet | str | Gmail preview |

### L1 — contacts.parquet (cross-account)

| Column | Type | Description |
|---------|------|-------------|
| email | str | Unique email |
| name | str | Display name (first seen) |
| domain | str | Email domain |
| first_seen | datetime | First email |
| last_seen | datetime | Last email |
| msg_count_from | int | Emails they sent |
| msg_count_to | int | Emails they received (in TO) |
| msg_count_cc | int | Times in CC |
| total_mentions | int | Total appearances |

### L1 — interactions.parquet (cross-account)

| Column | Type | Description |
|---------|------|-------------|
| from_email | str | Sender |
| to_email | str | Recipient |
| msg_count | int | Message count |
| thread_count | int | Distinct threads |
| first_date | datetime | First interaction |
| last_date | datetime | Last interaction |
| subjects_sample | str | Top 5 subjects (sep: " \|\|\| ") |

### L2 — relationship-scores.parquet

| Column | Type | Description |
|---------|------|-------------|
| email | str | Contact email |
| name | str | Name |
| domain | str | Domain |
| msgs_sent | int | Emails sent from the owner to this person |
| msgs_recv | int | Emails received from this person |
| total_msgs | int | Total |
| thread_count | int | Distinct threads |
| last_date | datetime | Last interaction |
| score | float | Score 0-100 (freq 40%, recency 30%, bidir 20%, depth 10%) |

## Scripts

| File | What it does | Command |
|------|---------|---------|
| `em-l0-auth.py` | Adds an OAuth account | `python3 tools/email/em-l0-auth.py acme` |
| `em-l0-download.py` | Bulk email download | `python3 tools/email/em-l0-download.py --account acme --workers 5` |
| `em-l1-enrich.py` | Builds contacts, interactions, threads | `python3 tools/email/em-l1-enrich.py` |
| `em-l2-export.py` | Builds network graph and scores | `python3 tools/email/em-l2-export.py --top 100` |
| `em-util-attachments.py` | Download attachments with filters | `python3 tools/email/em-util-attachments.py --account acme` |

## Full pipeline (for a new account)

```bash
# 1. Authentication
python3 tools/email/em-l0-auth.py acme

# 2. Download (parallel, automatic resume)
python3 tools/email/em-l0-download.py --account acme --since 2020-01-01 --workers 5

# 3. Enrichment (cross-account)
python3 tools/email/em-l1-enrich.py

# 4. Export for SBK
python3 tools/email/em-l2-export.py --top 100
```

## Mailboxes

| Account | Email | Scope | Status |
|---------|-------|-------|--------|
| acme | you@acme.example | 100% email + attachments | demo |
| globex | you@globex.example | 100% email, no attachments | demo |
| northwind | you@northwind.example | 100% email, no attachments | demo |

## Results (example demo run)

| Layer | File | Rows | Notes |
|-------|------|-------|------|
| L0 | acme/messages.parquet | 100 | demo |
| L0 | globex/messages.parquet | 100 | demo |
| L0 | northwind/messages.parquet | 100 | demo |
| L0 | **Total email** | **~300** | |
| L0 | acme/attachments/ | a few dozen files | pdf, docx, xlsx |
| L1 | contacts.parquet | ~100 | Unique cross-account contacts |
| L1 | interactions.parquet | ~200 | Relationship graph edges |
| L1 | threads.parquet | ~150 | Reconstructed threads |
| L2 | relationship-scores.parquet | ~100 | Score 0-100 (noise filtered) |
| L2 | network-graph.json | 100 | Top 100 relationships |

## Technical notes

- **Rate limit**: batch of 20 (1 worker) or 10 (multi-worker), delay 1.5-2s
- **Resume**: if the download is interrupted, rerun the same command — it resumes automatically
- **Disk footprint**: roughly a couple of MB per 1000 email
- **Throughput**: on the order of tens of messages per second with 5 workers
- **Deps**: google-api-python-client, google-auth-oauthlib, pandas, pyarrow
