import abc
from typing import Protocol, TypedDict

from jira import JIRA


class JiraTicket(TypedDict):
    issue: str
    title: str
    description: str
    creator: str


class Task(Protocol):
    @staticmethod
    @abc.abstractmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        raise NotImplementedError
