import abc
from typing import Protocol, TypedDict

from jira import JIRA


class JiraTicket(TypedDict):
    title: str
    description: str
    creator: str


class Task(Protocol):
    @abc.abstractmethod
    @staticmethod
    def can_handle(jira_issue: JiraTicket) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    @staticmethod
    def execute(jira: JIRA, jira_issue: JiraTicket) -> bool:
        raise NotImplementedError
