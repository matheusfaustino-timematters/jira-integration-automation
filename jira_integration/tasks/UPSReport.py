import csv
import io
import time as time_sleep

from jira import JIRA
from loguru import logger
from server import Server, ServerFactory

from jira_integration.settings import Settings
from jira_integration.types import (
    JiraAssignUsers,
    JiraTicket,
    JiraTransitionCodes,
    Task,
)

POWERSHELL_BREAKLINE_CHAR = "`n"

CMD_CREATE_CSV = '"{csv_content}" | Out-File -FilePath "{csv_filepath}" -Encoding utf8'

STATUS_IN_PROGRESS = "3"

CSV_PATH = "D:\\SAS\\SASUSER\\Versand_Daily\\CS_UPS_SCS_Dell_Last_Invoice\\Sources\\Invoicenumbers.csv"

CMD_TASK_RUN_STR = 'Start-ScheduledTask -TaskName "{task_name}" -TaskPath "{task_path}" | ConvertTo-Csv -NoTypeInformation'
CMD_TASK_STATUS_STR = 'Get-ScheduledTask | Where-Object {{ $_.TaskPath -like "{task_path}\\*" -and $_.TaskName -eq  "{task_name}" }} | ConvertTo-Csv -NoTypeInformation'


class UPSReport(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        # get the manual info from the class
        task_settings = Settings.get_task_setting("UPSReport")

        condition = (
            "ups" in jira_issue["title"].lower()
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
        # print("UPSReport")

        logger.info(f"Running UPSReport task on {jira_issue['issue']}")
        server: Server = ServerFactory.retrieve_server("tm-sasb2")

        issue_number = jira_issue["issue"]
        ticket_jira = jira.issue(issue_number)

        if ticket_jira.fields.status.id != STATUS_IN_PROGRESS:
            jira.transition_issue(
                jira_issue["issue"], JiraTransitionCodes.IN_PROGRESS.value
            )

        attachments = ticket_jira.fields.attachment
        invoice_numbers: list[str] = []
        for attach in attachments:
            if "pdf" in attach.filename.lower():
                number = attach.filename[:-4]
                invoice_numbers.append(number)

        has_att_with_no_invoice = any([not x.isdigit() for x in invoice_numbers])
        if len(invoice_numbers) > 0 and has_att_with_no_invoice:
            logger.warn(
                f"{jira_issue['issue']} Skipping process because attachment has no invoice"
            )

            return False

        # if not len(attachments) == 1:
        #     msg = f"For issue {issue_number} UPS ticket does not contain one attachment, might need some adjustments"
        #     jira.add_comment(
        #         jira_issue["issue"],
        #         msg,
        #         is_internal=True,
        #     )
        #     logger.error(msg)
        #     raise Exception(msg)

        # rename the period to match sas folder
        # ups_number = ticket_jira.fields.attachment[0].filename[:-4]

        logger.info(
            f"Found in {jira_issue['issue']} - {len(invoice_numbers)} invoice numbers"
        )

        invoice_number_str = POWERSHELL_BREAKLINE_CHAR.join(invoice_numbers)
        csv_content = f"ordernumber{POWERSHELL_BREAKLINE_CHAR}{invoice_number_str}"

        logger.info(f"{jira_issue['issue']}: saving CSV file for invoices")
        _ = server.run_ps_cmd(
            CMD_CREATE_CSV.format(csv_content=csv_content, csv_filepath=CSV_PATH)
        )

        task_name = "AdHoc_UPS_Dell_Month_Invoice"
        output_bytes = server.run_ps_cmd(
            CMD_TASK_RUN_STR.format(task_name=task_name, task_path="\\")
        )

        # assume running state because window cmd do not return anything when triggering the task on shell
        state = "Running"
        while state == "Running":
            logger.info(f"Check if task '{task_name}' still running")
            time_sleep.sleep(10)
            output_bytes = server.run_ps_cmd(
                CMD_TASK_STATUS_STR.format(task_name=task_name, task_path="")
            )
            cmd_result = UPSReport._get_result(output_bytes)
            state = cmd_result["State"]

        logger.info(
            f"{jira_issue['issue']}: Task '{task_name}' finished with status '{state}'"
        )
        is_success = state == "Ready"
        if is_success:
            jira.add_comment(
                jira_issue["issue"],
                ":robot: BipBop finished task without errors",
                is_internal=True,
            )
            jira.transition_issue(
                jira_issue["issue"], JiraTransitionCodes.RESOLVE_THIS_ISSUE.value
            )

    @staticmethod
    def _get_result(output_bytes: bytes) -> dict:
        # tricky to get the result from powershell in semi-organized way
        output = csv.DictReader(io.StringIO(output_bytes.decode("latin-1")))
        return next(output)
