from typing import NamedTuple
import re
from celline.config import Config

class TemplateManager:
    @staticmethod
    def replace_from_file(file_name: str, structure: NamedTuple, replaced_path: str):
        with open(
            f"{Config.EXEC_ROOT}/celline/template/content/{file_name}",
            "r",
            encoding="utf-8",
        ) as file:
            data = file.read()
        # shebang = f"#!/usr/bin/env {os.path.basename(os.environ.get('SHELL', '/bin/sh'))}\n"
        # data = shebang + data
        for field in structure._fields:
            data = re.sub(f"%{field}/", getattr(structure, field), data)

        with open(replaced_path, "w", encoding="utf-8") as file:
            file.write(data)
