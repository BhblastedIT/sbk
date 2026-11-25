# Attio CRM Pipeline — SBK

## What it does

Downloads the entire Attio CRM (objects, lists, notes, meetings, call recordings,
transcripts, tasks) and produces normalized parquet/JSON for SBK.

## Data architecture

```
~/.sbk-data/attio/
├── companies.parquet              ← demo records, dozens of columns (multi-value fixed)
├── people.parquet                 ← demo records, dozens of columns
├── deals.parquet                  ← demo records, dozens of columns
├── companies-raw.json             ← raw JSON (debug)
├── people-raw.json
├── deals-raw.json
├── notes.parquet                  ← notes
├── meetings.parquet               ← meetings
├── call-recordings.parquet        ← recording metadata
├── transcripts/                   ← one JSON per call recording
│   ├── {meeting_id}.json
│   └── ...
├── tasks.parquet                  ← tasks
├── lists-meta.json
├── list-a.parquet                 ← demo list
├── list-b.parquet                 ← demo list
├── list-c.parquet                 ← demo list
├── metadata/
│   ├── attributes-companies.json  ← all attributes with type and options
│   ├── attributes-people.json     ← all attributes
│   ├── attributes-deals.json      ← all attributes
│   ├── workspace-members.json     ← lookup UUID → name/email
│   ├── deal-pipeline-stages.json  ← the deal pipeline stages
│   └── select-options.json        ← all select values per object/attribute
└── lookups/
    ├── company-names.json         ← {record_id: "Company Name"}
    ├── people-names.json          ← {record_id: "Full Name"}
    └── people-emails.json         ← {record_id: "user@example.com"}
```

## Main schemas

### companies/people/deals.parquet

| Column | Type | Note |
|---------|------|------|
| record_id | str | Attio UUID |
| created_at | datetime | |
| web_url | str | Link to the Attio app |
| name | str | Record name |
| categories | str | Multi-select, separated by `\|\|\|` |
| team | str | Record-ref UUID, `\|\|\|` sep if multiple |
| primary_location | str | Address string |
| primary_location_lat | float | Latitude (if available) |
| primary_location_lon | float | Longitude (if available) |
| first_email_interaction | datetime | First email timestamp |
| last_email_interaction | datetime | Last email timestamp |
| ... | | ~50-65 columns total per object |

**Flatten conventions:**
- Multi-select → `value1|||value2|||value3`
- Record-reference → UUID (resolvable via lookups/)
- Location → string + `_lat`/`_lon` separate columns
- Interaction → timestamp `interacted_at`
- Actor-reference → workspace member UUID (resolvable via metadata/workspace-members.json)

### notes.parquet

| Column | Type |
|---------|------|
| note_id | str |
| parent_object | str (people/companies) |
| parent_record_id | str |
| title | str |
| content_plaintext | str |
| content_markdown | str |
| created_by_type | str (workspace-member/api-token/app) |
| created_by_id | str |
| created_at | datetime |

### meetings.parquet

| Column | Type |
|---------|------|
| meeting_id | str |
| title | str |
| description | str |
| start_dt | datetime |
| end_dt | datetime |
| is_all_day | bool |
| participants | str (email list, `\|\|\|` sep) |
| participant_count | int |
| linked_record_ids | str (`\|\|\|` sep) |
| created_at | datetime |

### call-recordings.parquet

| Column | Type |
|---------|------|
| recording_id | str |
| meeting_id | str |
| meeting_title | str |
| meeting_date | str |
| duration_seconds | float |
| url | str |
| created_at | datetime |

### transcripts/{meeting_id}.json

```json
{
  "meeting_id": "...",
  "recording_id": "...",
  "meeting_title": "...",
  "meeting_date": "...",
  "segments": [
    {"speaker": "Name", "text": "...", "start": 0.0, "end": 5.2}
  ],
  "raw_transcript": "full text"
}
```

### tasks.parquet

| Column | Type |
|---------|------|
| task_id | str |
| content | str |
| is_completed | bool |
| deadline_at | datetime |
| linked_record_ids | str (`\|\|\|` sep) |
| assignee_ids | str (`\|\|\|` sep) |
| created_at | datetime |

## Usage

```bash
# Full export (bottleneck = transcript scan)
python3 tools/attio/at-l0-download.py

# Export individual sections
python3 tools/attio/at-l0-download.py --only objects
python3 tools/attio/at-l0-download.py --only lists
python3 tools/attio/at-l0-download.py --only notes
python3 tools/attio/at-l0-download.py --only meetings
python3 tools/attio/at-l0-download.py --only transcripts   # includes meetings + recording scan
python3 tools/attio/at-l0-download.py --only tasks
python3 tools/attio/at-l0-download.py --only metadata
python3 tools/attio/at-l0-download.py --only lookups        # requires objects already downloaded
```

## Env

```
ATTIO_API_KEY  — Attio API key (or read from ~/.claude.json mcpServers.attio)
```

## Verify

```bash
python3 -c "
import pandas as pd
from pathlib import Path
d = Path.home() / '.sbk-data/attio'
for f in sorted(d.glob('*.parquet')):
    df = pd.read_parquet(f)
    print(f'{f.name}: {len(df)} rows, {len(df.columns)} cols')
"
```

## Timing

The dominant cost is the per-recording transcript scan; everything else
(objects, lists, notes, meetings, tasks, metadata, lookups) is a small number of
paginated API calls. Total runtime scales with the number of call recordings.
