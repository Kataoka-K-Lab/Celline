def as_r_bool(boolean: bool):
    if boolean:
        return "TRUE"
    return "FALSE"


def as_r_NULL(obj):
    if obj is None:
        return "NULL"
    return obj


def as_r_nullablestr(obj):
    if obj is None:
        return "NULL"
    return f"{obj}"
