import inspect
from os import name
from typing import Any, Generic, Type, TypeVar, overload

from celline.plugins.collections.generic import (DictionaryC, KeyValuePair,
                                                 ListC)
from celline.plugins.reflection.bindingflags import BindingFlags
from celline.plugins.reflection.method import MethodInfo
from celline.plugins.reflection.property import PropertyInfo

T = TypeVar("T")


class TypeC:
    __T: type
    __cached_prop = DictionaryC[type, ListC[PropertyInfo]]()
    __resistered_method = DictionaryC[type, ListC[MethodInfo]]()

    def __init__(self, clsdef: Any) -> None:
        """ Do not use this constructor.\n
        please use typeof(T) or <moduleinstance>.GetType()
        """
        if isinstance(clsdef, type):
            self.__T = clsdef
        pass

    def __eq__(self, o: object) -> bool:
        if isinstance(o, TypeC):
            return o.ModuleName == self.ModuleName and o.FullName == self.FullName
        return False

    @staticmethod
    def resister(tin: type, method: MethodInfo):
        """ Used for System.\n
        Resister given method for `tin`
        """
        res = TypeC.__resistered_method[tin]
        if res is None:
            res = ListC[MethodInfo]()
            TypeC.__resistered_method.Add(tin, res)
        res.Add(method)

    @property
    def BuiltinType(self):
        """ Returns default type
        """
        return self.__T

    @property
    def BaseType(self):
        """ Gets the type from which the current `TypeC` directly inherits.
        """
        return typeof[T](self.__T.__base__).TypeInfo

    @property
    def Name(self):
        """ Gets the name of the current member.
        """
        return self.__T.__name__

    @property
    def FullName(self):
        """ Gets the fully qualified name of the type, including its module.
        """
        return self.__T.__module__ + "+" + self.Name

    @property
    def ModuleName(self):
        """ Module name of the type.\n
        If you get new module, run `Module(typeinstance.ModuleName)`
        """
        return self.__T.__module__

    @property
    def IsAbstract(self):
        """ Gets a value indicating whether the TypeC is abstract and must be overridden.
        """
        return inspect.isabstract(self.__T)

    @property
    def IsAync(self):
        """ Gets a value indicating whether the TypeC is async.
        """
        return inspect.isasyncgen(self.__T)

    @property
    def IsBuiltin(self):
        """ Gets a value indicating whether the TypeC is built-in type.
        """
        return inspect.isbuiltin(self.__T)

    @property
    def IsCoroutine(self):
        """ Gets a value indicating whether the TypeC is coroutine type.
        """
        return inspect.iscoroutine(self.__T)

    def GetProperty(self, name: str, bindingAttr: BindingFlags = BindingFlags.Public):
        """ Searches for the specified property, using the specified binding constraints
        @[Optional]bindingAttr: All, Public, Private (default is Public) `BindingFlags.~~`\n
        [Usage]\n
        `typeinstance.GetProperty("name of the property", BindingFlags.Public)`
        """
        return self.GetProperties(bindingAttr).Where(
            lambda data: data.Name == name).First()

    def GetProperties(self, bindingAttr: BindingFlags = BindingFlags.Public):
        """ Searches for the class variables defined for the current `TypeC`, using the specified binding constraints.
        @[Optional]bindingAttr: All, Public, Private (default is Public)`BindingFlags.~~`\n
        [Usage]\n
        `typeinstance.GetProperties(BindingFlags.Public)`
        """
        cached = TypeC.__cached_prop[self.__T]
        if cached is not None:
            return cached
        attributes = ListC(inspect.getmembers(
            self.__T, lambda a: not (inspect.isroutine(a))))
        if bindingAttr == BindingFlags.Public:
            attributes.Where(lambda a: not (a[0].startswith("__")) and not (
                a[0]).startswith("_" + self.__T.__name__ + "__") and not (
                a[0]) == "_abc_impl")
        elif bindingAttr == BindingFlags.Private:
            attributes.Where(lambda a: a[0].startswith("__") or (
                a[0]).startswith("_" + self.__T.__name__ + "__"))
        data =\
            attributes\
            .Select(lambda prop: PropertyInfo(KeyValuePair(prop[0], prop[1]), self.__T))
        TypeC.__cached_prop.Add(self.__T, data)
        return data

    def GetDynamicProperties(self, instance: object, bindingAttr: BindingFlags = BindingFlags.Public):
        """ Searches for dynamically defined class variables in current Type C.
        Detects newly defined properties in the instance.
        @[Optional]bindingAttr: All, Public, Private (default is Public)`BindingFlags.~~`\n
        [Usage]\n
        `typeinstance.GetDynamicProperties(searchobject, BindingFlags.Public)`
        """
        attributes = ListC(inspect.getmembers(
            instance, lambda a: not (inspect.isroutine(a))))
        if bindingAttr == BindingFlags.Public:
            attributes.Where(lambda a: not (a[0].startswith("__")))
        elif bindingAttr == BindingFlags.Private:
            attributes.Where(lambda a: a[0].startswith("__"))
        return attributes\
            .Select(lambda prop: PropertyInfo(KeyValuePair(prop[0], prop[1]), self.__T))

    def GetMethods(self, bindingAttr: BindingFlags = BindingFlags.Public):
        """ Returns all the methods of the current `TypeC`\n
        @[Optional]bindingAttr: All, Public, Private (default is Public)`BindingFlags.~~`\n
        [Usage]\n
        `typeinstance.GetMethods(BindingFlags.Public)`
        """
        resisterd = TypeC.__resistered_method[self.__T]
        attributes = \
            ListC(inspect.getmembers(self.__T, inspect.isroutine))
        if bindingAttr == BindingFlags.Public:
            attributes.Where(lambda a: not (a[0].startswith("__")))
        elif bindingAttr == BindingFlags.Private:
            attributes.Where(lambda a: a[0].startswith("__"))
        li: ListC[MethodInfo] = ListC()
        for attr in attributes:
            li.Add(MethodInfo(KeyValuePair(attr[0], attr[1]), self.__T))
        if resisterd is not None:
            for res in resisterd:
                li.Add(res)
        return li

    def GetMethod(self, name: str, bindingAttr: BindingFlags = BindingFlags.Public):
        return self.GetMethods(bindingAttr)\
            .Where(lambda mt: mt.Name == name).First()


class typeof(Generic[T]):
    __T: type = type(T)
    __tinstance: TypeC = TypeC(None)

    def __init__(self, t: type) -> None:
        if isinstance(t, type):
            self.__T = t
            mod = __import__(t.__module__, fromlist=[t.__name__])
            self.__tinstance = TypeC(getattr(mod, t.__name__))
        elif isinstance(t, object):
            self.__T = type(t)
            mod = __import__(self.__T.__module__, fromlist=[self.__T.__name__])
            self.__tinstance = TypeC(getattr(mod, self.__T.__name__))
        pass

    def __eq__(self, o: object) -> bool:
        if not isinstance(o, typeof):
            return False
        return self.__T == o.__T

    @ property
    def TypeInfo(self):
        """ Get type information
        """
        return self.__tinstance
