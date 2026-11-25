# Organization Rules

Reference for naming, file placement and the data pipeline. This is a generic
starting point; adapt the tables to the sources you actually enable.

## 1. Principles

- Data stays local by default.
- Keep each file in one predictable location.
- Keep agent instructions free of facts that change; point to commands instead.

## 2. Data layout

- Runtime data lives under `~/.sbk-data/`, never inside the repository.
- Group data by organization and project, for example
  `~/.sbk-data/<org>/<project>/`.
- In git go only scripts, structure, pipeline, cron and the docs about how SBK works.

## 3. Naming conventions

### 3.1 Tool naming

A source tool is named `{source}-{stage}-{what}.py`, for example `em-l0-download.py`
(email, stage L0, download). The prefix is a short 2-4 letter code per source.

### 3.2 Organizations and aliases

Each organization has a short slug. Projects live under their organization.

### 3.3 Data roots

Runtime data lives under `~/.sbk-data/`, never inside the repository.

## 4. Sources

| code | source |
|---|---|
| `em` | email |
| `ca` | calendar |
| `sl` | slack |
| `wa` | whatsapp |
| `no` | notion |
| `gd` | gdrive |
| `li` | linkedin |
| `pl` | plaud |
| `tq` | tactiq |
| `at` | attio |
| `ds` | docusign |
| `pe` | personio |

## 5. Stages

| code | stage |
|---|---|
| `l0` | download raw data |
| `l1` | normalize and enrich |
| `l2` | cross-source knowledge extraction |
| `l3` | coverage and knowledge layer |
