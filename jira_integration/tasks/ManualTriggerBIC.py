from jira import JIRA

from jira_integration.types import JiraTicket, Task


class ManualTriggerBIC(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        return False

    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        pass
