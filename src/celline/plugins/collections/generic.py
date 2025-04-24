import json
from json.decoder import JSONDecodeError
from typing import Any, Callable, Generic, List, TypeVar, Union, overload

from celline.plugins.collections.enumrable import Enumrable

T1 = TypeVar('T1')
T2 = TypeVar('T2')
TResult = TypeVar("TResult")


class ListC(Generic[T1]):
    """ ## Supports Generic List like C#
    Usage:
    `li = List[Type]()` Create new List instance \n
    `li.Add(obj)` Example: Add element \n
    """
    __value = []

    @staticmethod
    def Range(count: int, fn: Callable[[int], T1]):
        li: List[T1] = []
        for i in range(count):
            li.append(fn(i))
        return li

    @staticmethod
    def FromJson(src: Union[str, bytes]):
        try:
            li: list = json.loads(src)
        except JSONDecodeError as je:
            raise je
        instance = ListC[T1]()
        instance.__value = li
        return instance

    @staticmethod
    def FromString(src: str, devider: str):
        return ListC(src.split(devider))

    def __init__(self, other: List[T1] = []) -> None:
        """ Create a given type List.
        @other: Other built-in-list
        """
        self.__i = 0
        self.__value = []
        for arg in other:
            self.__value.append(arg)

    def __iter__(self):
        return self

    def __next__(self) -> T1:
        if self.__i == len(self.__value):
            raise StopIteration()
        value = self.__value[self.__i]
        self.__i += 1
        return value

    def __getitem__(self, index: int):
        if index >= self.Length:
            return None
        data: T1 = self.__value[index]
        return data

    def Add(self, value: T1):
        """ Add value to self object  \n
        @*args: Initial element of given type\n
        [Usage]\n
        `instance.Add(MyClass())`
        """
        self.__value.append(value)
        return self

    def AddOn(self, fn: Callable[[], T1]):
        """ Add value to self object  \n
        @fn: on add\n
        [Usage]\n
        `instance.AddOn(lambda: Mylass())`
        """
        self.Add(fn())
        return self

    def AddRange(self, *values: Union[T1, None]):
        """ Add value to self object  \n
        @*args: Initial element of given type\n
        [Usage]\n
        `instance.AddRange(MyClass(), MyClass(), ...)`
        """
        for value in values:
            self.__value.append(value)
        return self

    def AddRangeOn(self, fn: Callable[[], List[T1]]):
        """ Add value to self object  \n
        @fn: on add\n
        [Usage]\n
        `instance.AddRangeOn(lambda: ListC.Range(10, lambda c: MyClass())))`
        """
        for t1 in fn():
            self.Add(t1)
        return self

    def Clear(self):
        """ Clear all values from the List \n
        [Usage]\n
        `instance.Clear()`
        """
        self.__value = []
        return self

    def Contains(self, value: T1):
        """ Returns where `value` is contained on the List
        @value: search target\n
        @returns: Contains? \n
        [Usage]\n
        `instance.Conatins(myclass)`
        """
        return self.__value.__contains__(value)

    def CountOf(self, value: T1):
        """ Returns the number of `values` contained in the List
        @value: search target\n
        @returns: Count \n
        [Usage]\n
        `instance.Conatins(myclass)`
        """
        return self.__value.count(value)

    def CountOfOn(self, fn: Callable[[T1], bool]):
        """ Counts and returns the number of `True` returned in the anonymous function `fn`.
        @fn: function which returns Boolean value indicating whether to include in the count \n
        @returns: Count\n
        [Usage]\n
        `instance.CountOfOn(lambda cls: cls == 100)`
        """
        counter = 0
        for val in self.__value:
            if fn(val):
                counter = counter+1
        return counter

    def Copy(self):
        """ Copy this object.\n
        @returns: copied object\n
        [Usage]\n
        `other = instance.Copy()`
        """
        newobj = ListC[T1]()
        newobj.__value = self.__value.copy()
        return newobj

    def CopyTo(self, other):
        """ Copy to another instance\n
        @other: Other ListC[T] object. (`other` shoud be ListC[T] instance)\n
        @returns: self\n
        [Usage]\n
        `other: ListC[int]`\n
        `instance.CopyTo(other)`
        """
        if type(other) is ListC:
            other.__value = self.__value.copy()
        else:
            raise TypeError(
                "You cannot copy to this type of " + str(type(other)))
        return self

    def Except(self, *second: T1):
        """Except given object\n
        @*second: except target\n
        @returns: self\n
        [Usage]\n
        `instance.Except(1, 100)` // Except 1 and 100 from ListC\n
        If you except on lamda function, please use `instance.Where()` instead.
        """
        for value in second:
            self.__value.remove(value)
        return self

    def IndexOf(self, value: T1, start: int = 0, end: int = ...):
        """ Returns the index that contains value.\n
        @value: search target\n
        @[optional] start index\n
        @[optional] end index\n
        @returns: Index (If the element isn't contained, returns -1)\n
        [Usage]\n
        `instance.IndexOf(1, 100)` // Except 1 and 100 from ListC
        """
        if self.Contains(value) == False:
            return -1
        index = -1
        for i in range(len(self.__value)):
            if self.__value[i] == value:
                index = i
        return index

    def IndexOfOn(self, fn: Callable[[T1], bool]):
        """ Returns the index that contains value.\n
        @fn: Returns the index when the function in `fn` returns` True`.\n
        @returns: Index (If the element isn't contained, returns -1)\n
        [Usage]\n
        `instance.IndexOfOn(lambda cls: cls != 100)` // Extract the index of elements other than 100
        """
        counter = 0
        index = -1
        for val in self.__value:
            if fn(val):
                index = counter
            counter = counter+1
        return index

    def Insert(self, index: int, *values: T1):
        """ Insert the element `value`\n
        @index: insert index\n
        @value: insert value\n
        """
        for value in values:
            self.__value.insert(index, value)

    def LastIndexOf(self, value: T1, start: int = 0, end: int = ...):
        """ Returns the Index when counting from the back.
        @value: search target
        @[Optional] start: start index
        @[Optional] end: end index
        """
        if self.Contains(value) is False:
            return -1
        clone = self.__value.copy()
        clone.reverse()
        return clone.index(value, start, end)

    def Max(self, selector: Callable[[T1], int]):
        """　Returns max value of int selector.\n
        @selector: Selector to set int value
        """
        li = []
        for value in self.__value:
            li.append(selector(value))
        return max(li)

    def Min(self, selector: Callable[[T1], int]):
        """　Returns min value of int selector.\n
        @selector: Selector to set int value
        """
        li = []
        for value in self.__value:
            li.append(selector(value))
        return min(li)

    def OrderBy(self, selector: Callable[[T1], Union[int, str]]):
        """　Explicitly sort by the int or str returned by `fn`.\n
        @selector: Selector to order
        """
        self.__value = Enumrable.OrderBy(self.__value, selector)
        return self

    def OrderByDescending(self, selector: Callable[[T1], Union[int, str]]):
        """　Explicitly sort by the int or str returned by `fn`.\n
        @selector: Selector to order
        """
        self.OrderBy(selector).__value.reverse()
        return self

    def Remove(self, value: T1):
        """ Remove the element that matches `value`.
        @value: remove target\n
        ** The value of the object is rewritten directly **
        """

        self.__value.remove(value)

    def RemoveOn(self, fn: Callable[[T1], bool]):
        """ Delete only the elements that returned True with `fn`
        @fn: decides remove target\n
        ** The value of the object is rewritten directly **
        """
        for i in reversed(range(len(self.__value))):
            if fn(self.__value[i]):
                self.__value.pop(i)

    def RemoveAt(self, index: int):
        """ Delete only the elements that have designated index
        @index: index\n
        ** The value of the object is rewritten directly **
        """
        self.__value.pop(index)

    def RemoveRange(self, start: int = 0, end: int = ...):
        """ Delete only the elements that have designated index range
        @start: start index
        @end: end index\n
        ** The value of the object is rewritten directly **
        """
        for i in reversed(range(len(self.__value))):
            if start <= i and i <= end:
                self.__value.pop(i)

    def Reverse(self):
        """ Reverse the elements
        """
        self.__value.reverse()

    @ property
    def Length(self):
        """ The length of List
        """
        return len(self.__value)

    @ property
    def Values(self):
        """ Convert value to list[T1]
        """
        data = list[T1]()
        for val in self.__value:
            data.append(val)
        return data

    # Extended Methods
    def AllOf(self, fn: Callable[[T1], bool]):
        """ Returns True if all `fn` returns True.
        @fn: Function to decide
        """
        predicate = True
        for val in self.__value:
            if fn(val) is False:
                predicate = False
        return predicate

    def AnyOf(self, fn: Callable[[T1], bool]):
        """ Returns True if any of `fn` returns True.
        @fn: Function to decide
        """
        predicate = False
        for val in self.__value:
            if fn(val):
                predicate = True
        return predicate

    def Average(self, selector: Callable[[T1], int]):
        """ Averages the numbers returned by `selector`.
        @selector: Anonymous function that returns a number
        @exception: If the number of elements is 0, ZeroDivisionError will be raised.
        """
        if self.Length == 0:
            raise ZeroDivisionError
        sum = 0
        for val in self.__value:
            sum += selector(val)
        return sum/self.Length

    def First(self):
        """　Returns the first element.
        """
        if self.Length == 0:
            raise IndexError("Index out of range")
        else:
            obj: T1 = self.__value[0]
            return obj

    def FirstOn(self, fn: Callable[[T1], bool]):
        """　Returns the first element of which the return value of fn is True.
        """
        for val in self.__value:
            if fn(val):
                ret: T1 = val
                return ret
        return None

    def NotNone(self):
        """　Delete the element of `None`.\n
        """
        self.__value = [x for x in self.__value if x is not None]
        return self

    def Last(self):
        """ Get the last element.
        """
        if self.Length > 0:
            return None
        else:
            obj: T1 = self.__value[self.Length - 1]
            return obj

    def LastOn(self, fn: Callable[[T1], bool]):
        """ The last element in the condition that True is returned by `fn`
        """
        if self.Length <= 0:
            return None
        result = {}
        count = 0
        for val in self.__value:
            if fn(val):
                ret: T1 = val
                result[count] = ret
                count = count+1
        if len(result) == 0:
            return None

        result_conv: T1 = result[len(result) - 1]
        return result_conv

    def Where(self, fn: Callable[[T1], bool]):
        """ Only the elements whose `fn` condition returns True are extracted.
        """
        for i in reversed(range(len(self.__value))):
            if fn(self.__value[i]) is False:
                del self.__value[i]
        return self

    def ForEach(self, fn: Callable[[T1], Union[Any, None]]):
        """ Extract the element.
        @fn: p0> Iterated object
        """
        for i in range(len(self.__value)):
            data: T1 = self.__value[i]
            fn(data)
        return self

    def ForEachIf(self, onNotNone: Callable[[T1], None or Any], onNone: Callable[[], None or Any] = None):
        """Branches depending on whether the element is None or not, and extracts the element.
        """
        for val in self.__value:
            if (val is None) and (onNone is not None):
                onNone()
            else:
                onNotNone(val)
        return self

    def Sum(self, fn: Callable[[T1], int]):
        """ Sum the ints returned by `fn`.
        @fn: Anonymous function that specifies a int
        """
        sum = 0
        for val in self.__value:
            sum += fn(val)
        return sum

    def Join(self, fn: Callable[[T1], str], combiner: str = ""):
        """ Combine str.
        @fn: Anonymous function that specifies a string
        @[optional] combiner: A string between elements
        """
        joined: str = ""
        for i in range(self.Length):
            joined += fn(self.__value[i])
            if i != self.Length - 1:
                joined += combiner
        return joined

    def Select(self, selector: Callable[[T1], TResult]):
        """ Specify a variable with fn from the element and return a new List.
        @selector: Anonymous function to get
        """
        li: ListC[TResult] = ListC()
        for val in self.__value:
            li.Add(selector(val))
        return li

    def Set(self, fn: Callable[[T1, int], T1]):
        """ Set object value and return
        @fn: p0>Iterated object, p1>index
        """
        for i in range(len(self.__value)):
            self.__value[i] = fn(self.__value[i], i)
        return self

    # Serialize Util

    def ToJson(self, selector: Callable[[T1], Union[bool, int, float, complex, str, bytes]]):
        li = list()
        for val in self.__value:
            li.append(selector(val))
        return json.dumps(li)


class KeyValuePair(Generic[T1, T2]):
    __key: T1
    __value: T2

    def __init__(self, key: T1, value: T2):
        self.__key = key
        self.__value = value

    @ property
    def Key(self):
        return self.__key

    @ Key.setter
    def Key(self, key: T1):
        self.__key = key
        return

    @ property
    def Value(self):
        return self.__value

    @ property
    def ValueNotNone(self):
        if self.__value is None:
            raise NotImplementedError("value is None")
        return self.__value

    @ Value.setter
    def Value(self, value: T2):
        self.__value = value
        return


class DictionaryC(Generic[T1, T2]):
    """ ## Supports Generic Dictionary like C#
    #### Usage:
    `li = Dictionary[KeyType, ValueType]()` Create new List instance \n
    `li.Add(obj)` Example: Add element \n
    """
    __kp: ListC[KeyValuePair[T1, T2]] = ListC[KeyValuePair[T1, T2]]([])
    __keys: ListC[T1] = ListC([])
    __values: ListC[T2] = ListC([])

    A = TypeVar('A')

    def __init__(self) -> None:
        """ Create a given type Dictionary.
        """

    def __getitem__(self, key: T1):
        if self.__keys.Length == 0:
            return None
        index = self.__keys.IndexOf(key)
        if index == -1:
            return None
        return self.__values[index]

    def Add(self, key: T1, value: T2):
        """ Add value to self object  \n
        ** The value of the object is rewritten directly **
        @key: Key
        @value: Value
        """
        if key is None:
            return self
        if self.ContainsKey(key):
            return self
        self.__keys.Add(key)
        self.__values.Add(value)
        self.__kp.Add(KeyValuePair(key, value))
        return self

    def AddKP(self, kp: KeyValuePair[T1, T2]):
        if kp is None:
            return self
        if kp.Key is None:
            return self
        if self.ContainsKey(kp.Key):
            return self
        self.__keys.Add(kp.Key)
        self.__values.Add(kp.Value)
        self.__kp.Add(kp)

    def AddOn(self, selector: Callable[[], KeyValuePair[T1, T2]]):
        result = selector()
        self.Add(result.Key, result.Value)

    def AddRange(self, *pairs: KeyValuePair):
        """ Add values to self object  \n
        ** The value of the object is rewritten directly **
        @*pairs: ranged kv pair
        """
        for pair in pairs:
            self.Add(pair.Key, pair.Value)

    def AddRangeOn(self, selector: Callable[[], List[KeyValuePair[T1, T2]]]):
        for data in selector():
            self.Add(data.Key, data.Value)
        return self

    @property
    def PairList(self) -> ListC[KeyValuePair[T1, T2]]:
        """ Convert to a list of KeyValuePair.
        """
        return self.__kp

    def Clear(self):
        """ Clear all values from the Dictionary \n
        ** The value of the object is rewritten directly **
        """
        self.__keys.Clear()
        self.__values.Clear()
        self.__kp.Clear()

    def ContainsKey(self, key: T1):
        """ Returns where `key` is contained on the Dictionary
        @returns: Contains?
        """
        return self.__keys.Contains(key)

    def ContainsValue(self, value: T2):
        """ Returns where `value` is contained on the Dictionary
        @returns: Contains?
        """
        return self.__values.Contains(value)

    def CountKeyOf(self, key: T1):
        """ Returns the number of `key` contained in the Dictionary
        @returns: Count
        """
        return self.__keys.CountOf(key)

    def CountValueOf(self, value: T2):
        """ Returns the number of `value` contained in the Dictionary
        @returns: Count
        """
        return self.__values.CountOf(value)

    def CountOfOn(self, fn: Callable[[KeyValuePair[T1, T2]], bool]):
        """ Counts and returns the number of `True` returned in the anonymous function `fn`.
        @fn: function which returns Boolean value indicating whether to include in the count \n
        Usage:
        `lambda T1Obj: (func: bool)`
        @returns: Count
        """
        return self.PairList.CountOfOn(fn)

    def Copy(self):
        """ Copy this object.
        """
        newobj = DictionaryC[T1, T2]()
        newobj.__keys = self.__keys.Copy()
        newobj.__values = self.__values.Copy()
        newobj.__kp = self.__kp.Copy()
        return newobj

    def KeyIndexOf(self, key: T1, start: int = 0, end: int = ...):
        """ Returns the index that contains given key.
        @key: search target
        @[optional] start index
        @[optional] end index
        @returns: Index (If the element isn't contained, returns -1)
        """
        if self.ContainsKey(key) is False:
            return -1
        return self.__keys.IndexOf(key, start, end)

    def ValueIndexOf(self, value: T2, start: int = 0, end: int = ...):
        """ Returns the index that contains given value.
        @value: search target
        @[optional] start index
        @[optional] end index
        @returns: Index (If the element isn't contained, returns -1)
        """
        if self.ContainsValue(value) is False:
            return -1
        return self.__values.IndexOf(value, start, end)

    def IndexOfOn(self, fn: Callable[[KeyValuePair], bool]):
        """ Returns the index that contains value.
        @fn: Returns the index when the function in `fn` returns` True`.
        @returns: Index (If the element isn't contained, returns -1)
        """
        counter = 0
        index = -1
        for kp in self.__kp:
            if kp.Value is not None:
                if fn(kp):
                    index = counter
            counter += 1
        return index

    def Insert(self, index: int, key: T1, value: T2):
        """ Insert the element `value`
        @index: insert index
        @value: insert value
        """
        self.__keys.Insert(index, key)
        self.__values.Insert(index, value)
        self.__kp.Insert(index, KeyValuePair(key, value))

    def Remove(self, key: T1):
        """ Remove the element that matches `value`.
        @value: remove target
        """
        index = self.__keys.IndexOf(key)
        if index == -1:
            return
        self.__keys.RemoveAt(index)
        self.__values.RemoveAt(index)
        self.__kp.RemoveAt(index)

    def RemoveOn(self, fn: Callable[[KeyValuePair[T1, T2]], bool]):
        """ Delete only the elements that returned True with `fn`
        @fn: decides remove target\n
        """
        for val in self.PairList:
            if fn(val):
                self.Remove(val.Key)

    def RemoveAt(self, index: int):
        """ Delete only the elements that have designated index\n
        @index: index
        """
        if 0 <= index < self.Length:
            self.__keys.RemoveAt(index)
            self.__values.RemoveAt(index)
            self.__kp.RemoveAt(index)

    def RemoveRange(self, start: int = 0, end: int = ...):
        """ Delete only the elements that have designated index range
        @start: start index
        @end: end index
        """
        for i in reversed(range(self.__keys.Length)):
            if start <= i and i <= end:
                self.__keys.RemoveAt(i)
                self.__values.RemoveAt(i)
                self.__kp.RemoveAt(i)

    def Reverse(self):
        """ Reverse the elements\n
        ** The value of the object is rewritten directly **
        """
        self.__keys.Reverse()
        self.__values.Reverse()
        self.__kp.Reverse()

    @ property
    def Length(self):
        """ The length of List
        """
        return self.__keys.Length

    @ property
    def Keys(self):
        """ Get keys
        """
        return self.__keys

    @ property
    def Values(self):
        """ Get values
        """
        return self.__values

    @property
    def KeyValuePairs(self):
        """ Get key value pairs
        """
        return self.__kp

    # Extended Methods
    def AllOf(self, fn: Callable[[KeyValuePair], bool]):
        """ Returns True if all `fn` returns True.
        @fn: Function to decide
        """
        predicate = True
        for val in self.PairList:
            if fn(val) is False:
                predicate = False
        return predicate

    def AnyOf(self, fn: Callable[[KeyValuePair], bool]):
        """ Returns True if any of `fn` returns True.
        @fn: Function to decide
        """
        predicate = False
        for val in self.PairList:
            if fn(val):
                predicate = True
        return predicate

    def Average(self, fn: Callable[[KeyValuePair], int]):
        """ Averages the numbers returned by fn.
        @fn: Anonymous function that returns a number
        @exception: If the number of elements is 0, ZeroDivisionError will be raised.
        """
        if self.Length == 0:
            raise ZeroDivisionError
        sum = 0
        for val in self.PairList:
            sum += fn(val)
        return sum/self.Length

    def First(self):
        """　Returns the first element.
        """
        if self.Length == 0:
            return None
        return self.PairList.First()

    def FirstOn(self, fn: Callable[[KeyValuePair[T1, T2]], bool]):
        """　Returns the first element of which the return value of fn is True.
        """
        for val in self.PairList:
            if fn(val):
                return val
        return None

    def NotNone(self):
        """　Delete the element of `None`.
        """
        for i in reversed(range(self.__keys.Length)):
            if self.__values[i] is None:
                self.RemoveAt(i)
        return self

    def Last(self):
        """ Get the last element.
        """
        if self.Length == 0:
            return None
        return self.PairList[self.Length - 1]

    def LastOn(self, fn: Callable[[KeyValuePair[T1, T2]], bool]):
        """ The last element in the condition that True is returned by `fn`
        """
        return\
            self\
            .Copy()\
            .Where(lambda el: fn(el))\
            .Last()

    def Where(self, fn: Callable[[KeyValuePair[T1, T2]], bool]):
        """ Only the elements whose `fn` condition returns True are extracted.
        """
        li = self.PairList
        for i in reversed(range(self.Length)):
            kp = li[i]
            if kp is not None:
                if fn(kp) is False:
                    self.RemoveAt(i)
        return self

    def ForEach(self, fn: Callable[[KeyValuePair[T1, T2]], None or Any]):
        """ Extract the element.
        """
        for val in self.PairList:
            fn(val)
        return self

    def ForEachIf(self, onNotNone: Callable[[KeyValuePair[T1, T2]], None or Any], onNone: Callable[[], None or Any] = None):
        """Branches depending on whether the element is None or not, and extracts the element.
        """
        for val in self.PairList:
            if (val is None) and (onNone is not None):
                onNone()
            else:
                onNotNone(val)
        return self

    def Sum(self, fn: Callable[[KeyValuePair[T1, T2]], int]):
        """ Sum the ints returned by `fn`.
        @fn: Anonymous function that specifies a int
        """
        sum = 0
        for val in self.PairList:
            sum += fn(val)
        return sum

    def Join(self, fn: Callable[[KeyValuePair[T1, T2]], str], combiner: str = ""):
        """ Combine str.
        @fn: Anonymous function that specifies a string
        @[optional] combiner: A string between elements
        """
        joined: str = ""
        counter = 0
        for val in self.PairList:
            joined += fn(val)
            if counter < self.Length:
                joined += combiner
        return joined

    def Select(self, fn: Callable[[KeyValuePair[T1, T2]], TResult]):
        """ Specify a variable with fn from the element and return a new List.
        @fn: Anonymous function to get
        """
        li: ListC[TResult] = ListC()
        for val in self.__kp:
            li.Add(fn(val))
        return li
