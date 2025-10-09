import abc
import importlib
from pathlib import Path
from typing import List, Tuple

from jira import JIRA

from jira_integration.types import JiraTicket, Task


class TaskManager(abc.ABC):
    _tasks: List[Tuple[str, object]] = []

    @staticmethod
    def load_tasks() -> None:
        for task in Path(__file__).parent.rglob("./tasks/*.py"):
            spec = importlib.util.spec_from_file_location(task.stem, task)
            TaskManager._tasks.append(
                (task.stem, importlib.util.module_from_spec(spec))
            )
            spec.loader.exec_module(TaskManager._tasks[-1][1])

    @staticmethod
    def process_issue(jira: JIRA, jira_issue: JiraTicket) -> int:
        """-1 = no task found / 0 = success / 1 = failed"""

        return_value = -1
        for class_name, module in TaskManager._tasks:
            task: Task = getattr(module, class_name)

            if task.can_handle(jira_issue):
                executed = task.execute(jira, jira_issue)
                return_value = 0 if executed else 1

        return return_value
