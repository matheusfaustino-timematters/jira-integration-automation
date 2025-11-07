import csv
import io
import time as time_sleep
from datetime import datetime, time

from jira import JIRA
from loguru import logger
from server import Server, ServerFactory

from jira_integration.types import (
    JiraAssignUsers,
    JiraTicket,
    JiraTransitionCodes,
    Task,
)

REPORTS_PATH = "\\SAS Reports"
TASK_COPY_NAME = "AdHoc_SPL_BIC_5_Copy_Attachments"
TASK_SEND_NAME = "AdHoc_SPL_BIC_6_Send_Attachments"

CMD_TASK_RUN_STR = 'Start-ScheduledTask -TaskName "{task_name}" -TaskPath "{task_path}" | ConvertTo-Csv -NoTypeInformation'
CMD_TASK_STATUS_STR = 'Get-ScheduledTask | Where-Object {{ $_.TaskPath -like "{task_path}\\*" -and $_.TaskName -eq  "{task_name}" }} | ConvertTo-Csv -NoTypeInformation'


class ManualTriggerBIC(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        # @TODO how to handle duplicated tickets
        return (
            "Manual invoices AX sending in SPL_Invoices_for_BIC".lower()
            in jira_issue["title"].lower()
            and time(8, 00) <= datetime.now().time() <= time(9, 55)
        )

    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        logger.info(f"Running ManualTriggerBIC on ticket {jira_issue['issue']}")

        jira.assign_issue(jira_issue["issue"], JiraAssignUsers.MATHEUS.value)
        jira.transition_issue(
            jira_issue["issue"], JiraTransitionCodes.IN_PROGRESS.value
        )
        jira.add_comment(
            jira_issue["issue"],
            ":robot: BipBop is taking care of the issue",
            is_internal=True,
        )

        server = ServerFactory.retrieve_server("tm-sasb1")

        is_success = ManualTriggerBIC._run_tasks(server, TASK_COPY_NAME)
        if not is_success:
            # @TODO maybe do some error handling
            return False

        is_success = ManualTriggerBIC._run_tasks(server, TASK_SEND_NAME)
        if is_success:
            jira.add_comment(
                jira_issue["issue"],
                ":robot: BipBop finished task without errors",
                is_internal=True,
            )
            jira.transition_issue(
                jira_issue["issue"], JiraTransitionCodes.RESOLVE_THIS_ISSUE.value
            )

        return is_success

    @staticmethod
    def _run_tasks(server: Server, task_name: str) -> bool:
        logger.info(f"Running task '{task_name}'")

        output_bytes = server.run_ps_cmd(
            CMD_TASK_RUN_STR.format(task_name=task_name, task_path=REPORTS_PATH)
        )

        # assume running state because window cmd do not return anything when triggering the task on shell
        state = "Running"
        while state == "Running":
            logger.info(f"Check if task '{task_name}' still running")
            time_sleep.sleep(1)
            output_bytes = server.run_ps_cmd(
                CMD_TASK_STATUS_STR.format(task_name=task_name, task_path=REPORTS_PATH)
            )
            cmd_result = ManualTriggerBIC._get_result(output_bytes)
            state = cmd_result["State"]

        logger.info(f"Task '{task_name}' finished with status '{state}'")
        return state == "Ready"

    @staticmethod
    def _get_result(output_bytes: bytes) -> dict:
        # tricky to get the result from powershell in semi-organized way
        output = csv.DictReader(io.StringIO(output_bytes.decode("latin-1")))
        return next(output)
