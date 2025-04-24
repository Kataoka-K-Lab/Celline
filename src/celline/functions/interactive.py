import subprocess
from typing import Dict, List, Optional

from celline.config import Config
from celline.functions._base import CellineFunction
from celline.plugins.collections.generic import DictionaryC, ListC


class Interactive(CellineFunction):
    def register(self) -> str:
        return "interactive"

    def on_call(self, args: Dict[str, DictionaryC[str, Optional[str]]]):
        command = args["options"]["req_1"]
        if command is None:
            print("[ERROR] Please specify up or down.")
            quit()
        if command == "up":
            # __proc8080 = subprocess.run(
            #     "lsof -i -P | grep 8000",
            #     shell=True,
            #     stdout=subprocess.PIPE,
            #     stderr=subprocess.PIPE
            # )
            # __proc_num = __proc8080.stdout.decode()
            # if __proc_num != "":
            #     print(__proc_num)
            subprocess.run("pip install flask && pip install flask_cors", shell=True)
            back_proc = subprocess.Popen(
                f"python {Config.EXEC_ROOT}/celline/api/main.py {Config.EXEC_ROOT} {Config.PROJ_ROOT}",
                stdout=subprocess.PIPE,
                shell=True,
            )
            # front_proc = subprocess.Popen(
            #     f"cd {Config.EXEC_ROOT}/frontend && npm run serve",
            #     stdout=subprocess.PIPE,
            #     shell=True)

            back_proc.communicate()
