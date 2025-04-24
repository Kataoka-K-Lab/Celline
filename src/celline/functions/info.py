from typing import Dict, List, Optional

import celline.data.files as fs
from celline.functions._base import CellineFunction
from celline.plugins.collections.generic import DictionaryC, ListC


class Info(CellineFunction):
    def register(self) -> str:
        return "info"

    def on_call(self, args: Dict[str, DictionaryC[str, Optional[str]]]):
        options = args["options"]
        id = options["req_1"]
        if id is None:
            print("[ERROR] Please specify target ID")
            quit()
        data = fs.read_accessions()
        fetch = False
        if id.startswith("GSE"):
            if id in data["GSE"]:
                print(data["GSE"][id])
            else:
                fetch = True
        elif id.startswith("GSM"):
            if id in data["GSM"]:
                print(data["GSM"][id])
            else:
                fetch = True
        elif id.startswith("SRR"):
            if id in data["SRR"]:
                print(data["SRR"][id])
            else:
                fetch = True
        return
