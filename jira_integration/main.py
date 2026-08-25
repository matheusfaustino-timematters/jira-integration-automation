import argparse
import os
from datetime import datetime
from typing import cast

from dotenv import load_dotenv
from jira import JIRA
from loguru import logger
from pid import PidFile
from task_manager import TaskManager

from jira_integration.types import JiraTicket

load_dotenv(".env.local")

logger.add("jira_integration.log", rotation="50 MB")

JIRA_PROJECT_KEY = "SDDM"
BIC_MANUAL_INVOICES_TITLE = "Manual invoices AX sending in SPL_Invoices_for_BIC"


class Argument(argparse.Namespace):
    ticket: str | None


def _args() -> Argument:
    parse = argparse.ArgumentParser(description="Jira integration")
    parse.add_argument("-t", "--ticket", type=str)

    args = parse.parse_args()
    return cast(Argument, args)


def main():
    args = _args()
    TaskManager.load_tasks()

    jira = JIRA(
        server=os.getenv("JIRA_URL"),
        basic_auth=(
            os.getenv("JIRA_EMAIL"),
            os.getenv("JIRA_API_TOKEN"),
        ),  # type: ignore
    )

    logger.info(
        f"Getting non-assigned tickets from {JIRA_PROJECT_KEY} and waiting for support"
    )
    if args and args.ticket:
        batches = [[jira.issue(args.ticket)]]
    else:
        waiting_for_support_issues = jira.search_issues(
            f"project={JIRA_PROJECT_KEY} AND assignee is EMPTY AND  status = 'Waiting for Support'"
        )
        # separate batch: tickets this automation itself left In Progress (unassigned) while
        # polling for the BIC manual invoices to be fixed. Scoped by title so no other task
        # is ever exposed to an In Progress ticket.
        bic_poll_issues = jira.search_issues(
            f"project={JIRA_PROJECT_KEY} AND assignee is EMPTY AND status = 'In Progress' "
            f"AND summary ~ '{BIC_MANUAL_INVOICES_TITLE}'"
        )
        batches = [waiting_for_support_issues, bic_poll_issues]

    for issues in batches:
        # dedup is scoped per batch: a "Waiting for Support" ticket and an "In Progress" one
        # from a previous day can legitimately share the same templated description.
        tasks_processed: set = set()
        for issue in issues:
            task = jira.issue(issue.key)

            if task.fields.description in tasks_processed:
                logger.info(f"Issue skipped because it is duplicated: {issue.key}")
                continue

            tasks_processed.add(task.fields.description)

            ticket: JiraTicket = {
                "issue": issue.key,
                "title": task.fields.summary,
                "description": task.fields.description or "",
                "creator": task.fields.reporter.displayName,
                "creator_email": getattr(task.fields.reporter, "emailAddress", "")
                or "",
                "created": datetime.strptime(
                    task.fields.created, "%Y-%m-%dT%H:%M:%S.%f%z"
                ),
                "status": task.fields.status.name,
            }

            process_status = TaskManager.process_issue(jira, ticket)
            if process_status == -1:
                logger.info(f"No Task was trigger for this issue {task.key}")

            if process_status == 0:
                logger.info(f"Task trigger for {task.key}, check comments")

            if process_status == 1:
                logger.info(
                    f"Error happening when triggering {task.key}, check process and fix it"
                )


if __name__ == "__main__":
    with PidFile("jira_integration_") as _:
        main()
