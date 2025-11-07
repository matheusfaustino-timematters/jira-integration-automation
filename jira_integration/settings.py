from pathlib import Path
from typing import Dict, List, TypedDict

import yaml
from loguru import logger


class TaskSettingsType(TypedDict):
    enabled: bool


class SettingsType(TypedDict):
    jobs: Dict[str, TaskSettingsType]


class Settings(object):
    SETTINGS_FILE: Path = Path(__file__).parent.parent / "settings.yaml"
    settings: SettingsType = {"jobs": {}}

    @staticmethod
    def get_task_setting(task_name: str) -> TaskSettingsType:
        Settings._load_yaml()

        return Settings.settings["jobs"][task_name]

    @staticmethod
    def _load_yaml() -> None:
        if len(Settings.settings["jobs"].keys()) == 0:
            with Settings.SETTINGS_FILE.open("r") as f:
                try:
                    Settings.settings = yaml.safe_load(f)
                except yaml.YAMLError as err:
                    logger.error(err)
