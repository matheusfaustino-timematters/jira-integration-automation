import abc
from calendar import month
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Union

import pandas
from dotenv import load_dotenv
from loguru import logger
from winrm import Session
from winrm.protocol import Protocol


class Server(metaclass=abc.ABCMeta):
    """Set values to be able to change from local to remote access machine"""

    @abc.abstractmethod
    def get_file_content(self, file_path: str) -> bytes:
        raise NotImplementedError

    @abc.abstractmethod
    def get_list_of_files(
        self, directory: str, filter_function: Union[Callable, None]
    ) -> list[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def get_list_of_files_ps(
        self, directory: str, filter_wildcard: Union[str, None]
    ) -> list[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def get_tasks_list_csv(self) -> pandas.DataFrame:
        raise NotImplementedError

    @abc.abstractmethod
    def run_ps_cmd(self, command: str) -> bytes:
        raise NotImplementedError


class LocalServer(Server):
    """
    Mimic remote calls but with local direct access to it. Made to run the scripts independently of the machine
    """

    def get_file_content(self, file_path: str) -> bytes:
        return Path(file_path).read_bytes()

    def get_list_of_files(
        self, directory: str, filter_function: Union[Callable, None]
    ) -> list[str]:
        dir_path = Path(directory)
        list_files = [str(file) for file in dir_path.parent.rglob(dir_path.name)]

        if filter_function is not None:
            list_files = [file for file in list_files if filter_function(file)]
        return list_files

    def get_list_of_files_ps(
        self,
        directory: str,
        filter_wildcard: Union[str, None],
        is_one_file_per_folder: bool = True,
    ) -> list[str]:
        path_dir = Path(directory)
        # like this for legacy and compatibility reasons
        filter_wildcard = filter_wildcard if filter_wildcard else ""

        # used to cut some files
        six_month_ago = datetime.now() - timedelta(days=6 * 30)
        is_file_and_six_month_ago: Callable[[Path], bool] = (
            lambda f: f.is_file() and f.stat().st_mtime > six_month_ago.timestamp()
        )

        recent_files = [
            file
            for file in path_dir.rglob(filter_wildcard)
            if is_file_and_six_month_ago(file)
        ]
        sorted_files = sorted(
            recent_files, key=lambda x: x.stat().st_mtime, reverse=True
        )
        groups_filename = defaultdict(list)
        for file in sorted_files:
            groups_filename[file.parent].append(file)

        most_recent_per_dir = [group for group in groups_filename.values()]
        if is_one_file_per_folder:
            most_recent_per_dir = [
                max(group, key=lambda x: x.stat().st_mtime)
                for group in groups_filename.values()
            ]

        return [str(file) for file in most_recent_per_dir]

    def get_tasks_list_csv(self) -> pandas.DataFrame:
        raise NotImplementedError

    def get_list_of_files_and_modified_ps(
        self, directory: str, filter_wildcard: Union[str, None]
    ) -> list[list[str, str]]:
        dir_path = Path(directory)

        # datetime is like this to match remote access format
        return [
            [
                str(file),
                datetime.fromtimestamp(file.stat().st_mtime).strftime(
                    "%m/%d/%Y %I:%M:%S %p"
                ),
            ]
            for file in dir_path.parent.rglob(filter_wildcard)
        ]

    def run_ps_cmd(self, command: str) -> bytes:
        raise NotImplementedError


class WindowsServer(Server):
    _client: Protocol = None
    _session: Session = None
    _url: str = None
    _client_shell_id: str = None
    _CMD_FILE_CONTENT: str = 'type "{file}"'
    _CMD_LIST_DIR: str = 'dir /s /b "{directory}"'
    _CMD_PS_LIST_DIR_ONE_FILE_PER_FOLDER: str = (
        'Get-ChildItem -Path "{directory}" -Recurse {file_filter} | Where-Object {{ $_.LastWriteTime -ge (Get-Date).AddMonths(-6) }} | Sort-Object LastWriteTime -Descending | Group-Object DirectoryName | ForEach-Object {{ $_.Group | Select-Object  -First 1 -ExpandProperty FullName  }}'
    )
    _CMD_PS_LIST_DIR_FOLDER: str = (
        'Get-ChildItem -Path "{directory}" -Recurse {file_filter} | Where-Object {{ $_.LastWriteTime -ge (Get-Date).AddMonths(-6) }} | Sort-Object LastWriteTime -Descending | Group-Object DirectoryName | ForEach-Object {{ $_.Group | Select-Object -ExpandProperty FullName  }}'
    )
    _CMD_PS_LIST_DIR_WITH_LAST_MODIFIED: str = (
        'Get-ChildItem -Path "{directory}" -Recurse {file_filter} | Select-Object FullName, LastWriteTime | ConvertTo-Csv -NoTypeInformation'
    )
    # Get-ChildItem -Path "D:\SAS\Config\Lev1\SchedulingServer\sasadmin\" -Recurse -Filter *.log | Sort-Object LastWriteTime -Descending | Group-Object DirectoryName | ForEach-Object { $_.Group | Select-Object FullName, LastWriteTime -First 5 }
    _CMD_LIST_TASKS_CSV: str = "schtasks /nh /query /fo CSV /v"
    # _CMD_LIST_TASKS_CSV: str = 'schtasks /query /fo CSV /v'
    _CMD_PS_SCRIPT: str = """
    $tasks = Get-ScheduledTask | ForEach-Object {
        $task = $_
        $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath
        $actions = $task.Actions | ForEach-Object {
            [PSCustomObject]@{
                ActionType = $_.ActionType
                Command    = $_.Execute
                Arguments  = $_.Arguments
            }
        }

        $actionsList = $actions | ForEach-Object { $_.Command + " " + $_.Arguments }

        [PSCustomObject]@{
            TaskName      = $task.TaskName
            TaskPath      = $task.TaskPath
            State         = $task.State
            LastRunTime   = $info.LastRunTime
            NextRunTime   = $info.NextRunTime
            NumberOfMissedRuns = $info.NumberOfMissedRuns
            LastTaskResult = $info.LastTaskResult
            Actions       = $actionsList -join "; "
            Triggers      = $task.Triggers | ForEach-Object { $_.StartBoundary }
            Settings      = $task.Settings
            Description   = $task.Description
        }
    }

    $tasks | ConvertTo-Csv -NoTypeInformation
    """

    def __init__(self, url: str):
        # load the env now, instead of root level to not affect the user check
        load_dotenv()

        self._url = url
        user, password = self._get_user_pass()
        self._client = self._connect_to_windows_server(url, user, password)
        self._session = self._connection_windows_server_session(url, user, password)

    @staticmethod
    def _connect_to_windows_server(url: str, user: str, password: str) -> Protocol:
        return Protocol(
            endpoint=f"http://{url}:5985/wsman",
            transport="ntlm",
            username=user,
            password=password,
            server_cert_validation="ignore",
        )

    @staticmethod
    def _connection_windows_server_session(
        url: str, user: str, password: str
    ) -> Session:
        return Session(
            url,
            auth=(user, password),
            transport="ntlm",
            server_cert_validation="ignore",
        )

    @staticmethod
    def _get_user_pass() -> tuple[str, str]:
        import os

        return os.getenv("USER"), os.getenv("PASS")

    def get_file_content(self, file_path: str) -> bytes:
        self._client_shell_id = self._client_shell_id or self._client.open_shell()

        command_id = self._client.run_command(
            self._client_shell_id, self._CMD_FILE_CONTENT.format(file=file_path)
        )
        file_content, _, _ = self._client.get_command_output(
            self._client_shell_id, command_id
        )

        return file_content

    def get_list_of_files(
        self, directory: str, filter_function: Union[Callable, None]
    ) -> list[str]:
        self._client_shell_id = self._client_shell_id or self._client.open_shell()

        command_id = self._client.run_command(
            self._client_shell_id, self._CMD_LIST_DIR.format(directory=directory)
        )
        list_files, _, _ = self._client.get_command_output(
            self._client_shell_id, command_id
        )

        report_list = [
            line.strip().decode("latin-1") for line in list_files.splitlines()
        ]
        if filter_function is not None:
            report_list = [line for line in report_list if filter_function(line)]

        return report_list

    def get_list_of_files_ps(
        self,
        directory: str,
        filter_wildcard: Union[str, None],
        is_one_file_per_folder=True,
    ) -> list[str]:
        """it get files that were modified 6 months ago and get the newest one from each directory"""
        t = self._session.run_ps(
            self._CMD_PS_LIST_DIR_ONE_FILE_PER_FOLDER.format(
                directory=directory,
                file_filter=f"-Filter {filter_wildcard}" if filter_wildcard else "",
            )
            if is_one_file_per_folder
            else self._CMD_PS_LIST_DIR_FOLDER.format(
                directory=directory,
                file_filter=f"-Filter {filter_wildcard}" if filter_wildcard else "",
            )
        )

        list_files = [line.strip().decode("latin-1") for line in t.std_out.splitlines()]
        return list_files

    def get_list_of_files_and_modified_ps(
        self, directory: str, filter_wildcard: Union[str, None]
    ) -> list[list[str, str]]:
        import io

        import pandas

        t = self._session.run_ps(
            self._CMD_PS_LIST_DIR_WITH_LAST_MODIFIED.format(
                directory=directory,
                file_filter=f"-Filter {filter_wildcard}" if filter_wildcard else "",
            )
        )

        if t.std_out == "":
            return []

        files: pandas.DataFrame = pandas.read_csv(
            io.BytesIO(t.std_out), encoding="latin-1"
        )
        return files.values.tolist()

    def get_tasks_list_csv(self) -> pandas.DataFrame:
        import io

        import pandas

        df_cache = Path(__file__).parent / f"tasks_list_{self._url}.pkl"

        if not df_cache.exists():
            t = self._session.run_ps(self._CMD_PS_SCRIPT)
            tasks_list = pandas.read_csv(io.BytesIO(t.std_out), encoding="latin-1")
            tasks_list.to_pickle(df_cache)
        else:
            tasks_list = pandas.read_pickle(df_cache)

        return tasks_list

    def run_ps_cmd(self, command: str) -> bytes:
        t = self._session.run_ps(command)

        return t.std_out


class ServerFactory:
    """username used to identify that script is running on the server directly"""

    _REMOTE_USER: str = "adm-mf"

    @staticmethod
    def retrieve_server(server_name: str) -> Server:
        import getpass
        import socket

        # load variables for sharepoint
        load_dotenv()

        # is_running_on_remote_server_b1 = lambda: ServerFactory._REMOTE_USER in getpass.getuser() and 'b1' in server_name
        if socket.gethostname() == server_name:
            logger.info("Selecting LocalServer as connection")

            return LocalServer()

        logger.info("Selecting WindowsServer as connection")

        # user is not the one expected from the server, so it is running from a local machine and needs remote conn
        return WindowsServer(server_name)
