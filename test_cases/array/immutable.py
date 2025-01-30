import typing

from algopy import Bytes, ImmutableArray, String, Txn, UInt64, arc4, op, subroutine, urange


class MyTuple(typing.NamedTuple):
    foo: UInt64
    bar: bool
    baz: bool


class MyDynamicSizedTuple(typing.NamedTuple):
    foo: UInt64
    bar: String


class TwoBoolTuple(typing.NamedTuple):
    a: bool
    b: bool


class SevenBoolTuple(typing.NamedTuple):
    foo: UInt64
    a: bool
    b: bool
    c: bool
    d: bool
    e: bool
    f: bool
    g: bool
    bar: UInt64


class EightBoolTuple(typing.NamedTuple):
    foo: UInt64
    a: bool
    b: bool
    c: bool
    d: bool
    e: bool
    f: bool
    g: bool
    h: bool
    bar: UInt64


class NineBoolTuple(typing.NamedTuple):
    foo: UInt64
    a: bool
    b: bool
    c: bool
    d: bool
    e: bool
    f: bool
    g: bool
    h: bool
    i: bool
    bar: UInt64


class ImmutableArrayContract(arc4.ARC4Contract):
    @arc4.abimethod()
    def test_uint64_array(self) -> None:
        arr = ImmutableArray[UInt64]()
        assert arr.length == 0

        arr = arr.append(UInt64(42))
        assert arr.length == 1
        assert arr[-1] == 42

        arr = add_x(arr, UInt64(5))
        assert arr.length == 6
        assert arr[-1] == 4

        arr = arr.append(UInt64(43))
        assert arr.length == 7
        assert arr[-1] == 43
        assert arr[0] == 42

        arr = pop_x(arr, UInt64(3))
        assert arr.length == 4
        assert arr[-1] == 2

        arr = add_x(arr, UInt64(10))
        assert arr.length == 14
        assert arr[-1] == 9

        arr = arr.append(UInt64(44))
        assert arr.length == 15
        assert arr[-1] == 44

        arr = arr.replace(2, UInt64(23))
        assert arr.length == 15
        assert arr[2] == 23

        self.a = arr

    @arc4.abimethod()
    def test_bool_array(self, length: UInt64) -> None:
        arr = ImmutableArray[bool]()
        assert arr.length == 0

        for i in urange(length):
            arr = arr.append(i == Txn.num_app_args)

        assert arr.length == length

        if length > 0:
            assert not arr[0], "expected element 0 to be False"
        if length > 1:
            assert not arr[1], "expected element 1 to be False"
        if length > 2:
            assert arr[2], "expected element 2 to be True"
        if length > 3:
            assert not arr[length - 1], "expected last element to be False"

        self.g = arr
        if length:
            arr = arr.pop()
            assert arr.length == length - 1

    @arc4.abimethod()
    def test_fixed_size_tuple_array(self) -> None:
        arr = ImmutableArray[tuple[UInt64, UInt64]]()
        assert arr.length == 0

        for i in urange(5):
            arr = arr.append((i + 1, i + 2))

        assert arr.length == 5
        assert arr[0] == (UInt64(1), UInt64(2))
        assert arr[-1] == (UInt64(5), UInt64(6))

        arr = arr.pop()
        assert arr.length == 4
        assert arr[0] == (UInt64(1), UInt64(2))
        assert arr[-1] == (UInt64(4), UInt64(5))
        self.c = arr

    @arc4.abimethod()
    def test_fixed_size_named_tuple_array(self) -> None:
        arr = ImmutableArray[MyTuple]()
        assert arr.length == 0

        for i in urange(5):
            arr = arr.append(MyTuple(foo=i, bar=i % 2 == 0, baz=i * 3 % 2 == 0))

        assert arr.length == 5
        foo, bar, baz = arr[0]
        assert foo == 0
        assert bar
        assert baz
        self.d = arr

    @arc4.abimethod()
    def test_dynamic_sized_tuple_array(self) -> None:
        arr = ImmutableArray[tuple[UInt64, Bytes]]()
        assert arr.length == 0

        for i in urange(5):
            arr = arr.append((i + 1, op.bzero(i)))

        assert arr.length == 5
        for i in urange(5):
            assert arr[i][0] == i + 1, "expected 1st element to be correct"
            assert arr[i][1].length == i, "expected 2nd element to be correct"

        arr = arr.pop()
        assert arr.length == 4
        assert arr[0] == (UInt64(1), op.bzero(0)), "expected 1, 0"
        assert arr[-1] == (UInt64(4), op.bzero(3)), "expected 4, 3"
        self.e = arr

    @arc4.abimethod()
    def test_dynamic_sized_named_tuple_array(self) -> None:
        arr = ImmutableArray[MyDynamicSizedTuple]()
        assert arr.length == 0

        for i in urange(5):
            arr = arr.append(MyDynamicSizedTuple(foo=i + 1, bar=times(i)))

        assert arr.length == 5
        for i in urange(5):
            assert arr[i][0] == i + 1, "expected 1st element to be correct"
            assert arr[i][1] == times(i), "expected 2nd element to be correct"

        arr = arr.pop()
        assert arr.length == 4
        assert arr[0] == MyDynamicSizedTuple(UInt64(1), String()), "expected 1, 0"
        assert arr[-1] == MyDynamicSizedTuple(UInt64(4), String("   ")), "expected 4, 3"
        self.f = arr

    @arc4.abimethod()
    def test_bit_packed_tuples(self) -> None:
        arr2 = ImmutableArray[TwoBoolTuple]()
        arr7 = ImmutableArray[SevenBoolTuple]()
        arr8 = ImmutableArray[EightBoolTuple]()
        arr9 = ImmutableArray[NineBoolTuple]()
        assert arr2.length == 0
        assert arr7.length == 0
        assert arr8.length == 0
        assert arr9.length == 0

        for i in urange(5):
            arr2 = arr2.append(TwoBoolTuple(a=i == 0, b=i == 1))
            arr7 = arr7.append(
                SevenBoolTuple(
                    foo=i,
                    bar=i + 1,
                    a=i == 0,
                    b=i == 1,
                    c=i == 2,
                    d=i == 3,
                    e=i == 4,
                    f=i == 5,
                    g=i == 6,
                )
            )
            arr8 = arr8.append(
                EightBoolTuple(
                    foo=i,
                    bar=i + 1,
                    a=i == 0,
                    b=i == 1,
                    c=i == 2,
                    d=i == 3,
                    e=i == 4,
                    f=i == 5,
                    g=i == 6,
                    h=i == 7,
                )
            )
            arr9 = arr9.append(
                NineBoolTuple(
                    foo=i,
                    bar=i + 1,
                    a=i == 0,
                    b=i == 1,
                    c=i == 2,
                    d=i == 3,
                    e=i == 4,
                    f=i == 5,
                    g=i == 6,
                    h=i == 7,
                    i=i == 8,
                )
            )

        assert arr2.length == 5
        assert arr7.length == 5
        assert arr8.length == 5
        assert arr9.length == 5
        self.bool2 = arr2
        self.bool7 = arr7
        self.bool8 = arr8
        self.bool9 = arr9

    @arc4.abimethod()
    def test_args(
        self,
        arr1: ImmutableArray[UInt64],
        arr2: ImmutableArray[bool],
        arr3: ImmutableArray[MyTuple],
        arr4: ImmutableArray[MyDynamicSizedTuple],
    ) -> None:
        pass

    @arc4.abimethod()
    def test_uint64_return(self) -> ImmutableArray[UInt64]:
        return ImmutableArray(UInt64(1), UInt64(2), UInt64(3))

    @arc4.abimethod()
    def test_bool_return(self) -> ImmutableArray[bool]:
        return ImmutableArray(True, False, True, False, True)

    @arc4.abimethod()
    def test_tuple_return(self) -> ImmutableArray[MyTuple]:
        return ImmutableArray(MyTuple(UInt64(), True, False))

    @arc4.abimethod()
    def test_dynamic_tuple_return(self) -> ImmutableArray[MyDynamicSizedTuple]:
        return ImmutableArray(MyDynamicSizedTuple(UInt64(), String("Hello")))

    # TODO: nested arrays


@subroutine
def times(n: UInt64) -> String:
    result = String()
    for _i in urange(n):
        result += String(" ")
    return result


@subroutine
def add_x(arr: ImmutableArray[UInt64], x: UInt64) -> ImmutableArray[UInt64]:
    for i in urange(x):
        arr = arr.append(i)
    return arr


@subroutine
def pop_x(arr: ImmutableArray[UInt64], x: UInt64) -> ImmutableArray[UInt64]:
    for _i in urange(x):
        arr = arr.pop()
    return arr
