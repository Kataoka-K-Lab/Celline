from typing import Any, Callable, Generic, List, TypeVar, Union

T1 = TypeVar('T1')


class Enumerable(Generic[T1]):

    @staticmethod
    def OrderBy(arr: list, keyselector: Callable[[T1], Union[int, str]]) -> List[Any]:
        if len(arr) <= 1:
            return arr

        mid = len(arr) // 2
        # ここで分割を行う
        left = arr[:mid]
        right = arr[mid:]

        # 再帰的に分割を行う
        left = Enumerable.OrderBy(left, keyselector)
        right = Enumerable.OrderBy(right, keyselector)

        # returnが返ってきたら、結合を行い、結合したものを次に渡す
        return Enumerable.__merge(left, right, keyselector)

    @staticmethod
    def __merge(left: List, right: List, keyselector: Callable[[T1], Any]):
        merged = []
        l_i, r_i = 0, 0

        #   ソート済み配列をマージするため、それぞれ左から見ていくだけで良い
        while l_i < len(left) and r_i < len(right):
            # ここで=をつけることで安定性を保っている
            if keyselector(left[l_i]) <= keyselector(right[r_i]):
                merged.append(left[l_i])
                l_i += 1
            else:
                merged.append(right[r_i])
                r_i += 1

        # 上のwhile文のどちらかがFalseになった場合終了するため、あまりをextendする
        if l_i < len(left):
            merged.extend(left[l_i:])
        if r_i < len(right):
            merged.extend(right[r_i:])
        return merged
