import glob
import inspect
import importlib.util
from typing import Any, overload

from celline.plugins.collections.generic import ListC
from celline.plugins.reflection.bindingflags import BindingFlags
from celline.plugins.reflection.type import TypeC, typeof
import os

class Module:
    __mod: Any

    @overload
    def __init__(self, arg: str) -> None:
        pass

    @overload
    def __init__(self, arg: type):
        pass

    def __init__(self, arg: Any) -> None:
        if isinstance(arg, str):
            module_name = os.path.splitext(arg)[0]
            spec = importlib.util.spec_from_file_location(module_name, arg)
            if spec is None or spec.loader is None:
                raise ModuleNotFoundError(f"Could not found: {module_name}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.__mod = module
            # self.__mod = __import__(arg, fromlist=[arg])
        if isinstance(arg, type):
            self.__mod = __import__(arg.__module__, fromlist=[arg.__name__])
        pass

    def GetType(self, typeName: str):
        t = typeof(getattr(self.__mod, typeName))
        return t

    def GetTypes(self, bindingAttr: BindingFlags = BindingFlags.Public):
        li = ListC[TypeC]()
        for t in inspect.getmembers(self.__mod):
            attr = getattr(self.__mod, t[0])
            if isinstance(attr, type):
                typed = TypeC(attr)
                if typed.ModuleName == self.__mod.__name__:
                    if bindingAttr == BindingFlags.Public:
                        if typed.Name.startswith("__") == False:
                            li.Add(typed)
                    if bindingAttr == BindingFlags.Private:
                        if typed.Name.startswith("__"):
                            li.Add(typed)
                    if bindingAttr == BindingFlags.All:
                        li.Add(typed)
        return li

    @property
    def Name(self) -> str:
        return self.__mod.__name__

    @staticmethod
    def GetModules(dirs: str):
        # path.replace("\\", "/").replace("/", ".").replace(".py", "")
        return ListC([f for f in list(glob.glob(dirs + "/**.py", recursive=True)) if not f.startswith("__")]).Select(
            lambda path: Module(path)
        )
