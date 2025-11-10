from jira import JIRA
from loguru import logger

from jira_integration.settings import Settings
from jira_integration.types import JiraTicket, Task

POWERSHELL_BREAKLINE_CHAR = "`n"

CMD_CREATE_CSV = '"{csv_content}" | Out-File -FilePath "{csv_filepath}" -Encoding utf8'


class UPSReport(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        # get the manual info from the class
        task_settings = Settings.get_task_setting("UPSReport")

        condition = (
            "ups report" in jira_issue["title"].lower()
            and "mirjam" in jira_issue["creator"].lower()
        )

        if condition and not task_settings["enabled"]:
            logger.warning('Task "UPSReport" did not run because it is not enabled')
            return False

        return condition

    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        # https://time-matters.atlassian.net/jira/servicedesk/projects/SDDM/queues/custom/12/SDDM-6312
        # "ordernumber`n123123`n123123`n123123" | Out-File -FilePath "test.csv" -Encoding utf8
        print("UPSReport")
