import inspect
from typing import Any

from celline.plugins.collections.generic import KeyValuePair


class PropertyInfo:
    __prop: KeyValuePair[str, Any]
    __type: type

    def __init__(self, prop: KeyValuePair[str, Any], t: type) -> None:
        self.__prop = prop
        self.__type = t
        pass

    @property
    def Name(self):
        return self.__prop.Key

    @property
    def IsBuiltin(self):
        return inspect.isbuiltin(self.__prop.Value)

    @property
    def IsPublic(self):
        return not (self.__prop.Key.startswith("__")) and not (
            self.__prop.Key).startswith("_" + self.PropertyType.__name__ + "__") and not (
            self.__prop.Key) == "_abc_impl"

    @property
    def IsPrivate(self):
        return self.__prop.Key.startswith("__") or (
            self.__prop.Key).startswith("_" + self.PropertyType.__name__ + "__")

    __decided: type = type(None)

    @property
    def PropertyType(self) -> type:
        if self.__decided == type(None):
            if self.__prop.Value is None:
                self.__decided = type(Any)
            else:
                self.__decided = type(self.__prop.Value)
        return self.__decided

    def GetValue(self, obj: object = None):
        if obj is None:
            return getattr(self.__type, self.__prop.Key)
        else:
            return getattr(obj, self.__prop.Key)

    def SetValue(self, value: Any, obj: object = None):
        if obj is None:
            setattr(self.__type, self.__prop.Key, value)
        else:
            setattr(obj, self.__prop.Key, value)
