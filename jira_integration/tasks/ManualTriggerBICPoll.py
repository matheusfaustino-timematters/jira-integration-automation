from jira import JIRA
from loguru import logger
from server import Server, ServerFactory

from jira_integration.bic_manual_invoices import (
    already_sent_invoices,
    check_manual_files,
    is_past_ax_processing_cutoff,
    load_manual_rows,
    resolve_ticket_complete,
    run_copy_send_for_rows,
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
        already_sent = already_sent_invoices(jira, issue_key)
        to_send = [row for row in check.found if row.invoice_no not in already_sent]

        if to_send:
            logger.info(
                f"{issue_key}: {len(to_send)} newly found manual invoice(s), sending to AX"
            )
            server: Server = ServerFactory.retrieve_server("tm-sasb1")
            if not run_copy_send_for_rows(jira, issue_key, server, to_send):
                return False

        if check.all_found:
            resolve_ticket_complete(jira, issue_key)
            return True

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
