from jira import JIRA
from loguru import logger
from server import Server, ServerFactory

from jira_integration.bic_manual_invoices import (
    NOTIFIED_MARKER,
    TASK_UPDATE_AX_SENDING_NAME,
    MissingFile,
    already_notified_desiree,
    check_manual_files,
    format_missing_files_comment,
    format_missing_files_email_body,
    is_manual_excel_up_to_date,
    load_manual_rows,
    run_copy_send_and_resolve,
    run_update_ax_sending,
    send_missing_files_email,
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
        check = check_manual_files(rows)

        if check.all_found:
            logger.info(f"{issue_key}: all manual files found, triggering AX copy/send")
            return run_copy_send_and_resolve(jira, issue_key, server)

        logger.info(f"{issue_key}: {len(check.missing)} manual file(s) missing")
        return ManualTriggerBIC._run_unhappy_path(jira, issue_key, check.missing)

    @staticmethod
    def _run_unhappy_path(
        jira: JIRA, issue_key: str, missing: list[MissingFile]
    ) -> bool:
        jira.add_comment(
            issue_key,
            format_missing_files_comment(missing),
            is_internal=True,
        )

        if not already_notified_desiree(jira, issue_key):
            sent = send_missing_files_email(
                subject=f"[{issue_key}] Wrong file names in manual AX invoice attachments",
                message=format_missing_files_email_body(missing),
            )
            if sent:
                jira.add_comment(issue_key, NOTIFIED_MARKER, is_internal=True)
            else:
                jira.add_comment(
                    issue_key,
                    ":robot: Failed to send notification email to Desiree, check manually",
                    is_internal=True,
                )

        return True
