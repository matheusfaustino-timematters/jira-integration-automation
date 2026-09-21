from jira import JIRA
from loguru import logger
from server import Server, ServerFactory

from jira_integration.bic_manual_invoices import (
    TASK_UPDATE_AX_SENDING_NAME,
    is_manual_excel_up_to_date,
    load_manual_rows,
    run_manual_invoices_cycle,
    run_update_ax_sending,
)
from jira_integration.settings import Settings
from jira_integration.types import JiraTicket, JiraTransitionCodes, Task

TICKET_TITLE = "Manual invoices AX sending in SPL_Invoices_for_BIC"
STATUS_WAITING_FOR_SUPPORT = "Waiting for Support"


class ManualTriggerBIC(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        # get the manual info from the class
        task_settings = Settings.get_task_setting("ManualTriggerBIC")
        condition = (
            TICKET_TITLE.lower() in jira_issue["title"].lower()
            and jira_issue["status"].lower() == STATUS_WAITING_FOR_SUPPORT.lower()
        )

        if condition and not task_settings["enabled"]:
            logger.warning(
                'Task "ManualTriggerBIC" did not run because it is not enabled'
            )
            return False

        return condition

    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        issue_key = jira_issue["issue"]
        logger.info(f"Running ManualTriggerBIC on ticket {issue_key}")

        jira.transition_issue(issue_key, JiraTransitionCodes.IN_PROGRESS.value)

        server: Server = ServerFactory.retrieve_server("tm-sasb1")

        if not run_update_ax_sending(server):
            jira.add_comment(
                issue_key,
                f":robot: Failed while running '{TASK_UPDATE_AX_SENDING_NAME}', "
                "check the SAS scheduler manually",
                is_internal=True,
            )
            return False

        if not is_manual_excel_up_to_date():
            jira.add_comment(
                issue_key,
                ":robot: SPL_Invoices_for_AX_Sending.xlsx was not updated for today, "
                "check manually",
                is_internal=True,
            )
            return False

        rows = load_manual_rows()
        return run_manual_invoices_cycle(jira, issue_key, server, rows)
