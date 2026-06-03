import abc
from datetime import datetime
from enum import Enum
from typing import Protocol, TypedDict

from jira import JIRA


# this list was made by fetch jira codes using the python jira lib
class JiraTransitionCodes(Enum):
    RESPOND_CUSTOMER = 851
    IN_PROGRESS = 891
    ESCALATE = 921
    APPROVAL_NECESSARY = 951
    RESOLVE_THIS_ISSUE = 761
    CANCEL_REQUEST = 901
    PENDING = 871


class JiraAssignUsers(Enum):
    MATHEUS = "Matheus Faustino"


class JiraTicket(TypedDict):
    issue: str
    title: str
    description: str
    creator: str
    creator_email: str
    created: datetime


class Task(Protocol):
    @staticmethod
    @abc.abstractmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        raise NotImplementedError
