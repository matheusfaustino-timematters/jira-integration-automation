from jira import JIRA
from loguru import logger
from server import Server, ServerFactory

from jira_integration.bic_manual_invoices import (
    check_manual_files,
    is_past_ax_processing_cutoff,
    load_manual_rows,
    run_copy_send_and_resolve,
)
from jira_integration.settings import Settings
from jira_integration.types import JiraTicket, JiraTransitionCodes, Task

TICKET_TITLE = "Manual invoices AX sending in SPL_Invoices_for_BIC"
STATUS_IN_PROGRESS = "In Progress"


class ManualTriggerBICPoll(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        # get the manual info from the class
        task_settings = Settings.get_task_setting("ManualTriggerBICPoll")
        condition = (
            TICKET_TITLE.lower() in jira_issue["title"].lower()
            and jira_issue["status"] == STATUS_IN_PROGRESS
        )

        if condition and not task_settings["enabled"]:
            logger.warning(
                'Task "ManualTriggerBICPoll" did not run because it is not enabled'
            )
            return False

        return condition

    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        issue_key = jira_issue["issue"]
        logger.info(f"Running ManualTriggerBICPoll on ticket {issue_key}")

        rows = load_manual_rows()
        check = check_manual_files(rows)

        if check.all_found:
            logger.info(
                f"{issue_key}: all manual files now found, triggering AX copy/send"
            )
            server: Server = ServerFactory.retrieve_server("tm-sasb1")
            return run_copy_send_and_resolve(jira, issue_key, server)

        if not is_past_ax_processing_cutoff():
            logger.info(
                f"{issue_key}: {len(check.missing)} manual file(s) still missing, "
                "before cutoff, doing nothing"
            )
            return True

        logger.info(f"{issue_key}: past AX processing cutoff, cancelling ticket")
        jira.add_comment(
            issue_key,
            ":robot: Time for processing on AX is over for today. Only tomorrow.",
            is_internal=True,
        )
        jira.transition_issue(issue_key, JiraTransitionCodes.CANCEL_REQUEST.value)

        return True
