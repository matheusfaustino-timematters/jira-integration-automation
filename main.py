import os

from dotenv import load_dotenv
from jira import JIRA
from loguru import logger

load_dotenv(".env.local")

logger.add("jira_integration.log", rotation="50 MB")

JIRA_PROJECT_KEY = "SDDM"


def main():
    jira = JIRA(
        server=os.getenv("JIRA_URL"),
        basic_auth=(
            os.getenv("JIRA_EMAIL"),
            os.getenv("JIRA_API_TOKEN"),
        ),
    )

    logger.info(
        f"Getting non-assigned tickets from {JIRA_PROJECT_KEY} and waiting for support"
    )
    issues = jira.search_issues(
        f"project={JIRA_PROJECT_KEY} AND assignee is EMPTY AND  status = 'Waiting for Support'"
    )
    for issue in issues:
        task = jira.issue(issue.key)
        task_title = task.fields.summary
        task_desc = task.fields.description

        print(task_title)

        # @TODO plugin style list to run tasks https://stackoverflow.com/questions/50181878/dynamically-loading-objects-from-list-of-python-files
        # @TODO update status
        # trigger script to run things on servers based on the title
        # add comment with visibility
        # assign it to me, at first


if __name__ == "__main__":
    main()
