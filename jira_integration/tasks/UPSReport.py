from jira import JIRA

from jira_integration.types import JiraTicket, Task


class UPSReport(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        return (
            "ups report" in jira_issue["title"].lower()
            and "mirjam" in jira_issue["creator"].lower()
        )

    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        print("UPSReport")
