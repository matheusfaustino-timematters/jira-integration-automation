# Jira Integration — BipBop

A Jira automation bot ("BipBop") that monitors a service desk project and automatically handles routine support tickets, eliminating repetitive manual steps involving file inspection, server task execution, and ticket state management.

## How it works

On each run the bot:

1. Queries Jira for unassigned tickets in status **"Waiting for Support"** under project `SDDM`
2. Deduplicates tickets with identical descriptions
3. Passes each ticket through every registered **Task** handler
4. Each task declares whether it can handle the ticket (`can_handle`) and, if so, acts on it (`execute`) — adding comments, transitioning status, running remote PowerShell jobs, etc.

A `PidFile` guard prevents multiple instances from running concurrently.

## Architecture

```text
jira_integration/
├── main.py          # Entry point — polls Jira and feeds tickets to TaskManager
├── task_manager.py  # Dynamically loads and dispatches all Task implementations
├── server.py        # Server abstraction: LocalServer / WindowsServer (WinRM)
├── settings.py      # Reads settings.yaml to enable/disable tasks at runtime
├── types.py         # Shared types: JiraTicket, Task protocol, transition codes
└── tasks/
    ├── CancelCopyJobsTickets.py      # Auto-cancels copy-job false-alarm tickets
    ├── ManualTriggerBIC.py           # Triggers BIC invoice scheduled tasks
    ├── ReportsFalsePositiveCheck.py  # Validates SAS report error tickets
    ├── UPSReport.py                  # Processes UPS invoice report requests
    └── ThresholdExceeded.py          # Stub — not yet enabled
```

### Server abstraction

`ServerFactory.retrieve_server(hostname)` returns:

- **`LocalServer`** — plain filesystem/path access, used when the script runs directly on the target machine
- **`WindowsServer`** — connects via WinRM (NTLM) for remote PowerShell execution and file access

This lets tasks run unchanged in both local and remote environments.

### Adding a new task

1. Create `jira_integration/tasks/MyTask.py` with a class named `MyTask` that implements the `Task` protocol:

   ```python
   class MyTask(Task):
       @staticmethod
       def can_handle(jira_issue: JiraTicket) -> bool: ...

       @staticmethod
       def execute(jira: JIRA, jira_issue: JiraTicket) -> bool: ...
   ```

2. Add an entry in `settings.yaml`:

   ```yaml
   jobs:
     MyTask:
       enabled: true
   ```

`TaskManager` discovers tasks automatically via glob — no registration needed.

## Tasks

| Task | Trigger condition | What it does |
| --- | --- | --- |
| **ReportsFalsePositiveCheck** | Title contains `b1 fehler in ladelauf` | Downloads HTML attachment from the ticket, reads SAS scheduling logs on the Windows server, checks if reported job failures are real or false positives, then cancels or escalates accordingly |
| **ManualTriggerBIC** | Title matches `Manual invoices AX sending in SPL_Invoices_for_BIC` between 08:00–09:55 | Runs two scheduled tasks on `tm-sasb1` (`AdHoc_SPL_BIC_5_Copy_Attachments` → `AdHoc_SPL_BIC_6_Send_Attachments`) and resolves the ticket on success |
| **UPSReport** | Title contains `ups` AND creator is `mirjam` | Extracts PDF invoice numbers from attachments, writes a CSV to the server, triggers `AdHoc_UPS_Dell_Month_Invoice` on `tm-sasb2`, resolves on success |
| **CancelCopyJobsTickets** | Title contains `COPY_FROM_NISASB1` | Checks `tm-sasb1:8080/b1_table_jobs.html` for late copy problems; auto-cancels the ticket if none are found |
| **ThresholdExceeded** | *(disabled — stub only)* | Placeholder for SAS shipment threshold tickets |

## Setup

**Requirements:** Python ≥ 3.12.7, [uv](https://github.com/astral-sh/uv)

```bash
# Install dependencies into the project virtual environment
uv pip install -e .
```

### Environment variables

Copy `.env.local` (or create it) with:

```env
# Jira
JIRA_URL=https://your-org.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your_api_token

# Windows server credentials (used by WindowsServer / WinRM)
USER=domain\username
PASS=your_password
```

### Task toggles

Enable or disable individual tasks in `settings.yaml` without touching code:

```yaml
jobs:
  ReportsFalsePositiveCheck:
    enabled: true
  ManualTriggerBIC:
    enabled: false   # set true to activate
  UPSReport:
    enabled: true
  CancelCopyJobsTickets:
    enabled: true
  ThresholdExceeded:
    enabled: false
```

## Running

```bash
uv run jira_integration/main.py
```

Logs are written to `jira_integration.log` (rotates at 50 MB).

Schedule this with Task Scheduler or a cron job to poll Jira on a regular interval.
