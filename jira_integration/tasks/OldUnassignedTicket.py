import os
import sqlite3
from datetime import date, datetime, timedelta, timezone

import requests
from jira import JIRA
from loguru import logger

from jira_integration.settings import Settings
from jira_integration.types import JiraTicket, Task

EXCLUDED_CREATOR_EMAIL = "tm.it.sas@time-matters.com"

TABLE_NAME = "old_unassigned_ticket_log"


class OldUnassignedTicket(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        task_settings = Settings.get_task_setting("OldUnassignedTicket")

        age_threshold = timedelta(
            minutes=int(os.environ["OLD_UNASSIGNED_TICKET_AGE_MINUTES"])
        )
        now = datetime.now(timezone.utc)
        age = now - jira_issue["created"]
        is_weekday = now.weekday() < 5
        condition = (
            is_weekday
            and jira_issue["creator_email"].lower() != EXCLUDED_CREATOR_EMAIL
            and age >= age_threshold
        )

        if condition and not task_settings["enabled"]:
            logger.warning(
                'Task "OldUnassignedTicket" did not run because it is not enabled'
            )
            return False

        return condition

    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        logger.info(f"Running OldUnassignedTicket task on {jira_issue['issue']}")

        issue_key = jira_issue["issue"]
        today = date.today().isoformat()

        if OldUnassignedTicket._was_notified(issue_key, today):
            logger.info(f"{issue_key}: already notified today, skipping")
            return True

        issue_url = OldUnassignedTicket._build_issue_url(issue_key)
        sent = OldUnassignedTicket._send_teams_message(jira_issue["title"], issue_url)
        if not sent:
            return False

        OldUnassignedTicket._mark_notified(issue_key, today)

        return True

    @staticmethod
    def _build_issue_url(issue_key: str) -> str:
        base = os.environ["JIRA_URL"].rstrip("/")
        return f"{base}/browse/{issue_key}"

    @staticmethod
    def _send_teams_message(title: str, issue_url: str) -> bool:
        webhook_url = os.environ["OLD_UNASSIGNED_TICKET_TEAMS_WEBHOOK_URL"]
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": "Unassigned Jira ticket",
            "text": f"**{title}**\n\n[{issue_url}]({issue_url})",
        }

        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
        except requests.RequestException as err:
            logger.error(f"Failed to send Teams message: {err}")
            return False

        if not response.ok:
            logger.error(
                f"Teams webhook returned {response.status_code}: {response.text}"
            )
            return False

        return True

    @staticmethod
    def _connect() -> sqlite3.Connection:
        db_path = os.environ["JIRA_INTEGRATION_DB_PATH"]
        conn = sqlite3.connect(db_path)
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} ("
            "issue TEXT NOT NULL, "
            "notified_date TEXT NOT NULL, "
            "PRIMARY KEY (issue, notified_date))"
        )
        return conn

    @staticmethod
    def _was_notified(issue_key: str, notified_date: str) -> bool:
        with OldUnassignedTicket._connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {TABLE_NAME} WHERE issue = ? AND notified_date = ?",
                (issue_key, notified_date),
            ).fetchone()

        return row is not None

    @staticmethod
    def _mark_notified(issue_key: str, notified_date: str) -> None:
        with OldUnassignedTicket._connect() as conn:
            conn.execute(
                f"INSERT INTO {TABLE_NAME} (issue, notified_date) VALUES (?, ?)",
                (issue_key, notified_date),
            )
