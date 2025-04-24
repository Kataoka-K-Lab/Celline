from inspect import getattr_static
from typing import Any, Type

from celline.plugins.collections.generic import KeyValuePair
from celline.plugins.reflection.decorators import static


class MethodInfo:
    __prop: KeyValuePair[str, Any]
    __type: type

    def __init__(self, prop: KeyValuePair[str, Any], t: type) -> None:
        self.__prop = prop
        self.__type = t

    @property
    def Name(self):
        return self.__prop.Key

    def Invoke(self, instance: object = None, **args):
        retval: Any = None
        if len(args) == 0:
            if instance is None:
                retval = getattr(self.__type, self.__prop.Key)()
            else:
                retval = getattr(instance, self.__prop.Key)()
        else:
            if instance is None:
                retval = getattr(self.__type, self.__prop.Key)(**args)
            else:
                retval = getattr(instance, self.__prop.Key)(**args)
        return retval
