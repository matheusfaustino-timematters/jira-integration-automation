import csv
import io
from datetime import datetime
from encodings import latin_1

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

STEERING_TABLE_FOLDER_NAME = {"Reporting_Daily": "Report_Daily"}


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

        # update ticket information
        jira.assign_issue(jira_issue["issue"], JiraAssignUsers.MATHEUS.value)
        jira.transition_issue(
            jira_issue["issue"], JiraTransitionCodes.IN_PROGRESS.value
        )

        issue_number = jira_issue["issue"]
        ticket_jira = jira.issue(issue_number)
        attachments = ticket_jira.fields.attachment
        if not len(attachments) == 1:
            msg = f"For issue {issue_number} Fehler in Ladelauf ticket does not contain one attachment"
            jira.add_comment(
                jira_issue["issue"],
                msg,
                is_internal=True,
            )
            raise Exception(msg)

        # rename the period to match sas folder
        report_period = STEERING_TABLE_FOLDER_NAME.get(
            ticket_jira.fields.attachment[0].filename[:-5], None
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
        for _, row in tasks_check.iterrows():
            # format string to the pattern from SAS logs
            file_date_pattern_str = row["Begin_Run_Timestamp"].strftime("%Y%m%d")
            # filter out all logs that do not match the string
            files = server.get_list_of_files_ps(
                f"{B1_DIR_REPORT_LOGS_PATH}Prod_ETL_{report_period}*\\",
                filter_wildcard=f"{file_date_pattern_str}*.log",
            )

            # tricky to put all logs line in one array
            log = [
                line
                for file in files
                for line in server.get_file_content(file).decode("latin-1").splitlines()
            ]

            # get content of file
            job_name = row["Jobname"]

            # fancy way to get the next line with python at the same for
            for line, next_line in zip(log, log[1:] + log[:1]):
                # parse the string and try to find the job there
                found_starting_job_line = job_name in line
                if found_starting_job_line:
                    found_complete_job_line = job_name in next_line
                    if not found_complete_job_line:
                        msg = f"For issue {issue_number} logs are not in order, check manually"
                        raise Exception(msg)

                    status_pos = next_line.find("status=")
                    # count the status= string itself
                    status = next_line[status_pos + 7 : -1]

                    if status == "0" or status == "1":
                        comment = ":robot: The table finished with success"
                        jira.transition_issue(
                            jira_issue["issue"],
                            # JiraTransitionCodes.CANCEL_REQUEST.value,
                            JiraTransitionCodes.IN_PROGRESS.value,
                        )
                    else:
                        comment = ":robot: The table finished with an error. Please, check it."

                    jira.add_comment(
                        jira_issue["issue"],
                        comment,
                        is_internal=True,
                    )
                    return True

        # if it reached here, it is because it did not find the Table. Something is wrong check flow
        jira.add_comment(
            jira_issue["issue"],
            ":robot: Table not found in files I searched. Please, check manually check it and check robot flow",
            is_internal=True,
        )

        return False
