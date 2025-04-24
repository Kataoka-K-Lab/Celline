from dataclasses import dataclass, asdict


@dataclass
class Data:
    title: str
    description: str
    items: list
    metadata: dict


data = asdict(
    Data(
        title="Sample Title",
        description="Sample Description",
        items=["item1", "item2"],
        metadata={"key": "value"},
    )
)

template_path = f"{Config.EXEC_ROOT}/celline/template/template.vue"
export_path = f"{Config.EXEC_ROOT}/celline/frontend/src/App.vue"


with open(template_path, "r") as f:
    content = f.read()

for key, value in data.items():
    placeholder = f"%%{key}%%"
    if isinstance(value, dict):
        for sub_key, sub_value in value.items():
            sub_placeholder = f"%%{key}_{sub_key}%%"
            content = content.replace(sub_placeholder, str(sub_value))
    elif isinstance(value, list):
        content = content.replace(placeholder, str(value).replace("'", '"'))
    else:
        content = content.replace(placeholder, str(value))

with open(export_path, "w") as f:
    f.write(content)
import subprocess

subprocess.run(
    ["npm", "run", "build"], cwd=f"{Config.EXEC_ROOT}/celline/frontend", check=True
)
