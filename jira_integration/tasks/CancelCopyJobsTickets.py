import csv
import io
from datetime import datetime

import pandas as pd
import requests
from jira import JIRA
from loguru import logger
from server import Server, ServerFactory

from jira_integration.settings import Settings
from jira_integration.types import (
    JiraAssignUsers,
    JiraTicket,
    JiraTransitionCodes,
    Task,
)


class CancelCopyJobsTickets(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        # get the manual info from the class
        task_settings = Settings.get_task_setting("CancelCopyJobsTickets")

        # real validation. Doing like this to help to manually disabled the task if needed
        condition = "COPY_FROM_NISASB1".lower() in jira_issue["title"].lower()

        if condition and not task_settings["enabled"]:
            logger.warning(
                'Task "CancelCopyJobsTickets" did not run because it is not enabled'
            )
            return False

        return condition

    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        logger.info(f"{jira_issue['issue']}: Running CancelCopyJobsTickets task")

        issue_number = jira_issue["issue"]

        copy_jobs_has_copy_problems = (
            CancelCopyJobsTickets._table_jobs_has_copy_problems()
        )

        if copy_jobs_has_copy_problems:
            logger.info(
                f"{issue_number}: It was found a issue in the job copy. Manually check the ticket"
            )
            jira.add_comment(
                jira_issue["issue"],
                "Table job has problems with late copy. Please, check the table_job folder manually",
                is_internal=True,
            )

            return True

        logger.info(f"{issue_number}: Canceling ticket")
        jira.add_comment(
            jira_issue["issue"],
            "Checked Table_jobs and it was not late.",
            is_internal=True,
        )
        jira.assign_issue(jira_issue["issue"], JiraAssignUsers.MATHEUS.value)
        jira.transition_issue(
            jira_issue["issue"],
            JiraTransitionCodes.CANCEL_REQUEST.value,
        )

        return True

    @staticmethod
    def _table_jobs_has_copy_problems() -> bool:
        r = requests.get("http://tm-sasb1:8080/b1_table_jobs.html")
        if not r.ok:
            return True

        tables = pd.read_html(io.StringIO(r.text))
        table_copy = tables[2]

        item_not_copied = table_copy[table_copy["Is created in Time?"] == False]

        return len(item_not_copied) > 0
