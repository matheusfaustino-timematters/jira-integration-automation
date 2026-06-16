# Jira Automation — Task Scheduler

**Task path:** `\MF_Lineage\Jira Automation`

BipBop is a polling automation bot that monitors the `SDDM` Jira service desk project for unassigned tickets in status **"Waiting for Support"**. On each run it passes every qualifying ticket through a set of pluggable task handlers that inspect server state, run remote PowerShell jobs, post comments, transition ticket status, and fire Microsoft Teams alerts — eliminating the manual triage steps that would otherwise require human intervention for each routine request type.

## Schedule

| Trigger | Days / Start time | Repetition | Execution limit |
|---------|-------------------|------------|-----------------|
| Daily (calendar) | Every day at `07:30` | Every `5 min` for `12 h` (ends ~`19:30`) | `30 min` |

The 5-minute cadence ensures new tickets are picked up promptly throughout business hours; the 12-hour window covers the full working day from `07:30` to `19:30`.

## Command Invoked

```bat
@echo off
cd /d "%~dp0"

uv run .\jira_integration\main.py

if %ERRORLEVEL% neq 0 (
    echo Script failed with exit code %ERRORLEVEL%
    pause
)
```

Backed by [jira_integration/main.py](https://github.com/matheusfaustino-timematters/jira-integration-automation/blob/master/jira_integration/main.py) — the entry point of the `jira_integration` package, invoked via the [`uv`](https://github.com/astral-sh/uv) package manager which resolves the virtualenv automatically.

## Parameters

| Parameter | Value in this task | Description |
|-----------|-------------------|-------------|
| `-t` / `--ticket` | *(not set)* | Optional Jira issue key (e.g. `SDDM-123`). When provided, skips the full JQL search and processes only that ticket. Intended for manual one-off runs. |

## What the Command Does

On each invocation, `main.py`:

1. **Loads credentials** from `.env.local` — `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `USER`, `PASS`.
2. **Discovers and loads all Task handlers** dynamically from `jira_integration/tasks/` via glob — no manual registration required.
3. **Queries Jira** for unassigned "Waiting for Support" tickets in project `SDDM` using JQL:
   ```
   project=SDDM AND assignee is EMPTY AND status = 'Waiting for Support'
   ```
4. **Deduplicates** tickets with identical descriptions to avoid processing the same request submitted multiple times.
5. **For each ticket**, extracts issue key, summary, description, reporter display name, reporter email, and creation timestamp, then calls `TaskManager.process_issue()`.
6. **`TaskManager`** iterates all loaded and enabled task handlers, calling `can_handle()` on each. The first handler that matches executes; the result is logged with one of three status codes: `-1` (no handler matched), `0` (success), `1` (error).

**Task handlers** (toggleable at runtime via [settings.yaml](https://github.com/matheusfaustino-timematters/jira-integration-automation/blob/master/settings.yaml)):

| Task | Enabled | Trigger condition | Action |
|------|:-------:|-------------------|--------|
| [ReportsFalsePositiveCheck](https://github.com/matheusfaustino-timematters/jira-integration-automation/blob/master/jira_integration/tasks/ReportsFalsePositiveCheck.py) | ✅ | Title contains `b1 fehler in ladelauf` | Downloads HTML attachment from the ticket; reads SAS scheduling logs on the target Windows server via WinRM; cancels ticket if the job failure is a false positive, escalates otherwise |
| [UPSReport](https://github.com/matheusfaustino-timematters/jira-integration-automation/blob/master/jira_integration/tasks/UPSReport.py) | ✅ | Title contains `ups` AND creator is `mirjam` | Extracts PDF invoice numbers from the ticket attachment, writes a CSV to the server, triggers scheduled task `AdHoc_UPS_Dell_Month_Invoice` on `tm-sasb2`, resolves ticket on success |
| [CancelCopyJobsTickets](https://github.com/matheusfaustino-timematters/jira-integration-automation/blob/master/jira_integration/tasks/CancelCopyJobsTickets.py) | ✅ | Title contains `COPY_FROM_NISASB1` | Checks `tm-sasb1:8080/b1_table_jobs.html` for active late-copy problems; auto-cancels the ticket if none are found |
| [OldUnassignedTicket](https://github.com/matheusfaustino-timematters/jira-integration-automation/blob/master/jira_integration/tasks/OldUnassignedTicket.py) | ✅ | Weekday + ticket age ≥ `OLD_UNASSIGNED_TICKET_AGE_MINUTES` (currently `90 min`) + creator email ≠ `tm.it.sas@time-matters.com` | Posts a Microsoft Teams alert linking to the unassigned ticket; deduplicates via SQLite so each ticket is alerted at most once per calendar day |
| [ManualTriggerBIC](https://github.com/matheusfaustino-timematters/jira-integration-automation/blob/master/jira_integration/tasks/ManualTriggerBIC.py) | ❌ | Title matches `Manual invoices AX sending in SPL_Invoices_for_BIC`, time between `08:00`–`09:55` | Runs `AdHoc_SPL_BIC_5_Copy_Attachments` then `AdHoc_SPL_BIC_6_Send_Attachments` on `tm-sasb1`; resolves ticket on success |
| [ThresholdExceeded](https://github.com/matheusfaustino-timematters/jira-integration-automation/blob/master/jira_integration/tasks/ThresholdExceeded.py) | ❌ | *(stub — not implemented)* | Placeholder for future SAS shipment threshold ticket handling |

Remote server access (file reads, scheduled task execution) uses WinRM with NTLM auth via the `WindowsServer` abstraction in [server.py](https://github.com/matheusfaustino-timematters/jira-integration-automation/blob/master/jira_integration/server.py).

## Output

| Artifact | Location |
|----------|----------|
| Jira ticket comment | Appended to the Jira issue via REST API |
| Jira ticket status transition | Updated on the Jira issue via REST API |
| Teams alert (old unassigned ticket) | Microsoft Teams channel via webhook `OLD_UNASSIGNED_TICKET_TEAMS_WEBHOOK_URL` |
| Notification deduplication log | SQLite table `old_unassigned_ticket_log` in `jira_integration.db` (path from `JIRA_INTEGRATION_DB_PATH`) |
| Application log | `jira_integration.log` in `C:\Users\adm-mf\Documents\projects\jira-integration-automation\` (rotates at 50 MB) |

## Notes

- **`MultipleInstancesPolicy: IgnoreNew`** — if a run is still in progress when the next 5-minute trigger fires, the new trigger is silently discarded. No queuing, no error logged by Task Scheduler.
- **Execution limit: 30 minutes** — Task Scheduler forcibly terminates the process after 30 minutes. Given the 5-minute repetition, a hung run can block up to 6 consecutive trigger slots before being killed.
- **`PidFile` guard** — `main.py` creates a PID lock file (`jira_integration_*.pid`) at startup as a second-layer single-instance guard. A second process started simultaneously (e.g., via manual run) exits immediately without touching Jira.
- **`pause` on error in `start.bat`** — has no effect when Task Scheduler runs the task non-interactively. Only blocks if the bat is invoked from an interactive console session.
- **`OldUnassignedTicket` deduplication** — the SQLite table stores `(issue, notified_date)` pairs. A ticket that remains unassigned will re-alert once per calendar day.
- **Weekend suppression for `OldUnassignedTicket`** — `can_handle()` checks `datetime.weekday() < 5`; no Teams alerts are sent on Saturdays or Sundays.
- **`ManualTriggerBIC` and `ThresholdExceeded` are disabled** in `settings.yaml`. Flipping `enabled: false` → `enabled: true` activates them immediately on the next run — no code change or task restart needed.
- **Author:** `TDSD\adm-mf`. Task runs under stored-password credentials (`LogonType: Password`). If the account password is rotated, the Task Scheduler entry must be updated with the new password or the task will fail silently.
- **Task is not hidden** (no `<Hidden>true</Hidden>` element present in the XML export).
