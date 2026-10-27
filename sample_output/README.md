# Sample output

Real logs and output from running the solution against a Microsoft Entra **test tenant** with 251 fictional users (250 seeded + the tenant admin). Logs contain user IDs only.

| File | Run | Result | Shows |
|---|---|---|---|
| `sync_20261027_001808.log` | Dry run before admin consent | Graph returned **HTTP 403**; clear error, clean exit | Error handling |
| `sync_20261027_002249.log` | Dry run after consent | Token obtained, 1 user read and transformed | Authentication, GET, missing data |
| `sync_20261027_002617.log` | Seeding (setup only) | 250 test users created via Graph | Test data preparation |
| `sync_20261027_003416.log` | **Run 1** | 3 pages (100/100/51), **251 created**, 12 × 500 and 4 × 429 retried, **0 failed** | Pagination, POST, 429/500, retries |
| `sync_20261027_003809.log` | **Run 2** | **251 skipped (unchanged)**, nothing sent | Duplicate prevention |
| `sync_20261027_004029.log` | **Run 3** (after editing one user's department) | **1 updated**, 250 skipped | Change detection |
| `users.json` | Latest run | All transformed records in the target JSON format | JSON transformation |

Things to look for in the Run 1 log:
- `Graph page 1/2/3` lines: pagination
- `HTTP 500 | attempt 1/5, retrying in 1.4s` → `attempt 2/5, retrying in 2.2s`: exponential backoff
- `HTTP 429 (server asked to wait 2s via Retry-After)`, followed by success 2 seconds later
- `no mail, used userPrincipalName as email` / `missing fields set to null`: missing data
- The `Summary` block at the end
