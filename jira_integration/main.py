import os

from dotenv import load_dotenv
from jira import JIRA
from loguru import logger
from task_manager import TaskManager

from jira_integration.types import JiraTicket

load_dotenv(".env.local")

logger.add("jira_integration.log", rotation="50 MB")

JIRA_PROJECT_KEY = "SDDM"


def main():
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
    issues = jira.search_issues(
        f"project={JIRA_PROJECT_KEY} AND assignee is EMPTY AND  status = 'Waiting for Support'"
    )
    for issue in issues:
        task = jira.issue(issue.key)

        ticket: JiraTicket = {
            "title": task.fields.summary,
            "description": task.fields.description,
            "creator": task.fields.reporter.displayName,
        }

        process_status = TaskManager.process_issue(jira, ticket)
        # @TODO update status
        # trigger script to run things on servers based on the title
        # add comment with visibility
        # assign it to me, at first


if __name__ == "__main__":
    main()
