class classproperty:
    def __init__(self, fget=None, fset=None, fdel=None):
        self.fget = fget
        self.fset = fset
        self.fdel = fdel

    def __get__(self, owner_self, owner_cls):
        if self.fget is None:
            raise AttributeError("unreadable attribute")
        return self.fget(owner_cls)

    def __set__(self, owner_self, value):
        if self.fset is None:
            raise AttributeError("can't set attribute")
        # pylint: disable=not-callable
        self.fset(type(owner_self), value)

    def __delete__(self, owner_self):
        if self.fdel is None:
            raise AttributeError("can't delete attribute")
        # pylint: disable=not-callable
        self.fdel(type(owner_self))

    def getter(self, fget):
        return type(self)(fget, self.fset, self.fdel)

    def setter(self, fset):
        return type(self)(self.fget, fset, self.fdel)

    def deleter(self, fdel):
        return type(self)(self.fget, self.fset, fdel)
