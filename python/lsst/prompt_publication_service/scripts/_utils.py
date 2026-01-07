import re


def split_dataset_types_argument(argument: str) -> list[str]:
    return re.split(r"[\s,]+", argument)
