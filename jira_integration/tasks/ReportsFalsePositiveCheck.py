import csv
import io
from datetime import datetime

import pandas as pd
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

B1_DIR_REPORT_LOGS_PATH = "D:\\SAS\\Config\\Lev1\\SchedulingServer\\sasadmin\\"

STEERING_TABLE_FOLDER_NAME = {
    # "Reporting_Daily": "Report_Daily",
    "Reporting_Monthly": "Report_Monthly",
    "MDM": "MDM_OSScheduler",
    "SPL": "SPL_OSScheduler",
    "SELFBI-DATAMART": "SelfBI_Datamart",
    "CUBES": "Cubes_OSScheduler",
}

STEERING_TABLE_JOB_NAME = {"SLS_ZF_Global_Air_Freight_CO2": "SLS_ZF_Monthly_Shipments"}

STATUS_IN_PROGRESS = "3"


class ReportsFalsePositiveCheck(Task):
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        # get the manual info from the class
        task_settings = Settings.get_task_setting("ReportsFalsePositiveCheck")

        # real validation. Doing like this to help to manually disabled the task if needed
        condition = "b1 fehler in ladelauf" in jira_issue["title"].lower()

        if condition and not task_settings["enabled"]:
            logger.warning(
                'Task "ReportsFalsePositiveCheck" did not run because it is not enabled'
            )
            return False

        return condition

    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        logger.info(f"Running ReportsFalsePositiveCheck task on {jira_issue['issue']}")
        server: Server = ServerFactory.retrieve_server("tm-sasb1")

        has_access = ReportsFalsePositiveCheck._ping()
        if not has_access:
            logger.info(
                f"Running ReportsFalsePositiveCheck task on {jira_issue['issue']}: no VPN"
            )
            return False

        issue_number = jira_issue["issue"]
        ticket_jira = jira.issue(issue_number)

        # update ticket information
        # jira.assign_issue(jira_issue["issue"], JiraAssignUsers.MATHEUS.value)
        # id = 3 is In Progress as STATUS of the ticket (different than transition code)
        if ticket_jira.fields.status.id != STATUS_IN_PROGRESS:
            jira.transition_issue(
                jira_issue["issue"], JiraTransitionCodes.IN_PROGRESS.value
            )

        attachments = ticket_jira.fields.attachment
        if not len(attachments) == 1:
            msg = f"For issue {issue_number} Fehler in Ladelauf ticket does not contain one attachment"
            jira.add_comment(
                jira_issue["issue"],
                msg,
                is_internal=True,
            )
            logger.error(msg)
            raise Exception(msg)

        # rename the period to match sas folder
        attachment_extension = ticket_jira.fields.attachment[0].filename[-5:]
        if "pdf" in attachment_extension.lower():
            return False

        attachment_filename = ticket_jira.fields.attachment[0].filename[:-5]
        # if we do not have anything in the steering table, try with its own name
        report_period = STEERING_TABLE_FOLDER_NAME.get(
            attachment_filename, attachment_filename
        )

        # get HTML attachment from the ticket
        report_attachment = ticket_jira.fields.attachment[0].get()
        tables = pd.read_html(io.StringIO(report_attachment.decode("utf-8")))

        # make basic transformation to be easier to filter out
        job_table = tables[1]
        job_table["Status"] = job_table["Status"].apply(
            lambda x: int(x) if x.isdigit() else None
        )
        job_table["Begin_Run_Timestamp"] = job_table["Begin_Run_Timestamp"].apply(
            lambda x: datetime.strptime(x, "%d%b%y:%H:%M:%S")
        )

        tasks_check = job_table[job_table["Status"] != 0]
        tasks_amount = len(tasks_check)
        tasks_checked = 0
        # set status for non-success to change it inside
        tasks_status = 0
        for _, row in tasks_check.iterrows():
            logger.info(f"Searching {row['Jobname']}")

            # format string to the pattern from SAS logs
            file_date_pattern_str = row["Begin_Run_Timestamp"].strftime("%Y%m%d")
            # filter out all logs that do not match the string
            files = server.get_list_of_files_ps(
                f"{B1_DIR_REPORT_LOGS_PATH}Prod_ETL_{report_period}*\\",
                filter_wildcard=f"{file_date_pattern_str}*.log",
            )

            logger.info(f"Found {len(files)} files")

            # tricky to put all logs line in one array
            log = [
                line
                for file in files
                for line in server.get_file_content(file).decode("latin-1").splitlines()
            ]

            # get content of file (try to normalize it to match logs)
            job_name = (
                row["Jobname"].replace(" ", "").replace("- ", "").replace(" ", "_")
            )
            is_data_mart_job = "data mart".lower() in row["Jobname"].lower()
            if is_data_mart_job:
                job_name = row["Jobname"].replace(" ", "_").replace("_-_", "_")

            # workaround for inconsistent job's name in the logs and sas
            job_name = STEERING_TABLE_JOB_NAME.get(job_name, job_name)

            # fancy way to get the next line with python at the same for
            for line, next_line in zip(log, log[1:] + log[:1]):
                # parse the string and try to find the job there
                found_starting_job_line = job_name in line
                if found_starting_job_line:
                    found_complete_job_line = job_name in next_line
                    if not found_complete_job_line:
                        msg = f"For issue {issue_number} logs are not in order, check manually"
                        logger.error(msg)
                        raise Exception(msg)

                    status_pos = next_line.find("status=")
                    # count the status= string itself
                    status = next_line[status_pos + 7 : -1]

                    if status == "0" or status == "1":
                        comment = f":robot: The job {job_name} finished with success"
                        tasks_status = 0 if tasks_status == 0 else tasks_status
                    else:
                        tasks_status = 1
                        comment = f":robot: The job {job_name} finished with an error. Please, check it."

                    jira.add_comment(
                        jira_issue["issue"],
                        comment,
                        is_internal=True,
                    )
                    tasks_checked += 1
                    break

        # support for multiple tables check
        if tasks_checked == tasks_amount:
            if tasks_status == 0:
                logger.info(f"Canceling ticket {issue_number}")
                jira.transition_issue(
                    jira_issue["issue"],
                    JiraTransitionCodes.CANCEL_REQUEST.value,
                )

            return True

        # if it reached here, it is because it did not find the Table. Something is wrong check flow
        jira.add_comment(
            jira_issue["issue"],
            ":robot: Table not found in files I searched. Please, check manually check it and check robot flow",
            is_internal=True,
        )

        return False

    @staticmethod
    def _ping() -> bool:
        import requests

        url = "http://tm-sasb1:8080/"
        try:
            resp = requests.options(url)
            if resp.ok:
                return True
        except Exception as e:
            logger.error(e)

        return False
