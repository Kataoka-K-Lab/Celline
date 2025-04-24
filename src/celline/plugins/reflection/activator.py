from typing import Any, Generic, TypeVar, overload

from celline.plugins.reflection.type import TypeC, typeof

T = TypeVar("T")


class Activator:
    @staticmethod
    @overload
    def CreateInstance(t: typeof[T], *args: Any) -> T:
        ...

    @staticmethod
    @overload
    def CreateInstance(t: TypeC, *args: Any) -> Any:
        ...

    @staticmethod
    def CreateInstance(t: Any, *args: Any):
        if isinstance(t, typeof):
            if (len(args) == 0):
                return t.TypeInfo.BuiltinType()
            else:
                return t.TypeInfo.BuiltinType(args)
        if isinstance(t, TypeC):
            if (len(args) == 0):
                return t.BuiltinType()
            else:
                return t.BuiltinType(args)
