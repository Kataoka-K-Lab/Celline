from __future__ import annotations
import os
import subprocess
from typing import Any, Dict, Optional, Final
import toml


class Config:
    ## static ##
    runnings: Dict[str, Config] = {}
    """[Static] Running execution"""
    current: str = ""
    """[Static] Current execution"""
    ## objective ##
    EXEC_ROOT: Final[str] = os.path.dirname(os.path.dirname(__file__))
    PROJ_ROOT: Final[str]

    def __init__(self, project_root_path: str) -> None:
        # self.EXEC_ROOT = os.path.dirname(os.path.dirname(__file__))
        self.PROJ_ROOT = project_root_path
        Config.current = f"{self.EXEC_ROOT}+{self.PROJ_ROOT}"
        if Config.current not in Config.runnings:
            Config.runnings[Config.current] = self

    # @staticmethod
    # def initialize(exec_root_path: str, proj_root_path: str, cmd: str):
    #     Config.EXEC_ROOT = exec_root_path
    #     Config.PROJ_ROOT = proj_root_path
    #     if proj_root_path is None:
    #         return
    #     if cmd == "init":
    #         Setting.create_new()
    #     else:
    #         if not os.path.isfile(f"{proj_root_path}/setting.toml"):
    #             print("Could not find setting.toml in your project.")


class Setting:
    # model variables
    name: str
    version: str
    wait_time: int
    r_path: str = ""
    _r_path_initialized: bool = False  # Track if R path has been initialized
    # New execution settings
    system: str = "multithreading"  # "multithreading" or "PBS"
    nthread: int = 1
    pbs_server: str = ""
    # Custom functions settings
    custom_functions_dir: str = "functions"  # Directory for custom functions (relative to PROJ_ROOT)
    enable_custom_functions: bool = True  # Enable/disable custom function discovery

    # @staticmethod
    # def validate():
    #     if not os.path.isfile(f"{Config.PROJ_ROOT}/setting.toml"):
    #         raise FileNotFoundError("Could not find setting file in your project.")

    @staticmethod
    def as_dict():
        return {
            "project": {"name": Setting.name, "version": Setting.version},
            "fetch": {"wait_time": Setting.wait_time},
            "R": {"r_path": Setting.r_path},
            "execution": {
                "system": Setting.system,
                "nthread": Setting.nthread,
                "pbs_server": Setting.pbs_server,
            },
            "custom_functions": {
                "directory": Setting.custom_functions_dir,
                "enabled": Setting.enable_custom_functions,
            },
        }

    # @staticmethod
    # def as_cfg_obj(dict: Dict[str, Any]):
    #     Setting.name = dict["project"]["name"]
    #     Setting.version = dict["project"]["version"]
    #     Setting.wait_time = dict["fetch"]["wait_time"]
    #     Setting.r_path = dict["R"]["r_path"]

    # @staticmethod
    # def initialize():
    #     Setting.validate()
    #     with open(f"{Config.PROJ_ROOT}/setting.toml", mode="r") as f:
    #         Setting.as_cfg_obj(toml.load(f))

    # @staticmethod
    # def create_new():
    #     proc = subprocess.Popen("which R", stdout=subprocess.PIPE, shell=True)
    #     result = proc.communicate()
    #     default_r = result[0].decode("utf-8").replace("\n", "")
    #     questions = [
    #         inquirer.Text(name="projname", message="What is a name of your project?"),
    #         inquirer.Path(name="rpath", message="Where is R?", default=default_r),
    #     ]
    #     result = inquirer.prompt(questions, raise_keyboard_interrupt=True)
    #     if result is None:
    #         quit()
    #     Setting.name = result["projname"]
    #     Setting.r_path = result["rpath"]
    #     Setting.version = "0.01"
    #     Setting.wait_time = 4
    #     Setting.flush()
    #     print("Completed.")

    @staticmethod
    def ensure_r_path():
        """Ensure R path is initialized (lazy initialization)."""
        if not Setting._r_path_initialized and not Setting.r_path:
            try:
                # Try common R installation paths first (faster)
                common_paths = ["/usr/bin/R", "/usr/local/bin/R", "/opt/homebrew/bin/R"]
                for path in common_paths:
                    if os.path.exists(path) and os.access(path, os.X_OK):
                        Setting.r_path = path
                        Setting._r_path_initialized = True
                        return
                
                # Fallback to system search only if needed
                proc = subprocess.Popen(
                    "which R",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    shell=True,
                    timeout=2
                )
                result = proc.communicate()
                Setting.r_path = result[0].decode("utf-8").strip() or "/usr/bin/R"
            except (subprocess.TimeoutExpired, Exception):
                Setting.r_path = "/usr/bin/R"  # Default fallback
            finally:
                Setting._r_path_initialized = True

    @staticmethod
    def flush():
        with open(f"{Config.PROJ_ROOT}/setting.toml", mode="w", encoding="utf-8") as f:
            toml.dump(Setting.as_dict(), f)
