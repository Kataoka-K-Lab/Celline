import re
import sys

import toml


def main() -> None:
    """Parse the version and requires-python in the [project] section of pyproject.toml,
    parse the version and requires-python in the [project] section of pyproject.toml, and write them out as step output in GitHub Actions.
    """
    data = toml.load("pyproject.toml")
    version = data["project"]["version"]
    requires_python = data["project"].get("requires-python", ">=3.10")

    # 例: '>=3.10.12' のような形式から '3.10.12' 部分を抜き出す
    match = re.match(r"^>=?([0-9]+\.[0-9]+(\.[0-9]+)?)", requires_python)
    if match:  # noqa: SIM108
        python_version_for_ci = match.group(1)
    else:
        # 万一複雑な指定の場合は、運用に応じてより詳細なパースを行う
        python_version_for_ci = "3.10"

    # GitHub Actions のステップ出力用に標準出力へ
    # (If GITHUB_OUTPUT is directly echoed, it is assumed to be done on the bash side.)
    print(f"version={version}")  # noqa: T201
    print(f"python_version={python_version_for_ci}")  # noqa: T201


if __name__ == "__main__":
    main()
