import base64
import typing
from collections.abc import Collection, Iterable, Mapping, Sequence
from functools import cached_property

import attrs
from immutabledict import immutabledict

from puya import algo_constants, log
from puya.avm_type import AVMType
from puya.awst_build import constants
from puya.errors import CodeError, InternalError
from puya.parse import SourceLocation
from puya.utils import sha512_256_hash

logger = log.get_logger(__name__)


@attrs.frozen(kw_only=True)
class WType:
    name: str
    scalar_type: typing.Literal[AVMType.uint64, AVMType.bytes, None]
    "the (unbound) AVM stack type, if any"
    ephemeral: bool = False
    """ephemeral types are not suitable for naive storage / persistence,
     even if their underlying type is a simple stack value"""
    immutable: bool

    def __str__(self) -> str:
        return self.name


void_wtype: typing.Final = WType(
    name="void",
    scalar_type=None,
    immutable=True,
)

bool_wtype: typing.Final = WType(
    name="bool",
    scalar_type=AVMType.uint64,
    immutable=True,
)

uint64_wtype: typing.Final = WType(
    name="uint64",
    scalar_type=AVMType.uint64,
    immutable=True,
)

biguint_wtype: typing.Final = WType(
    name="biguint",
    scalar_type=AVMType.bytes,
    immutable=True,
)

bytes_wtype: typing.Final = WType(
    name="bytes",
    scalar_type=AVMType.bytes,
    immutable=True,
)
string_wtype: typing.Final = WType(
    name="string",
    scalar_type=AVMType.bytes,
    immutable=True,
)
asset_wtype: typing.Final = WType(
    name="asset",
    scalar_type=AVMType.uint64,
    immutable=True,
)

account_wtype: typing.Final = WType(
    name="account",
    scalar_type=AVMType.bytes,
    immutable=True,
)

application_wtype: typing.Final = WType(
    name="application",
    scalar_type=AVMType.uint64,
    immutable=True,
)

state_key: typing.Final = WType(
    name="state_key",
    scalar_type=AVMType.bytes,
    immutable=True,
)
box_key: typing.Final = WType(
    name="box_key",
    scalar_type=AVMType.bytes,
    immutable=True,
)


@attrs.frozen
class _TransactionRelatedWType(WType):
    transaction_type: constants.TransactionType | None
    ephemeral: bool = attrs.field(default=True, init=False)
    immutable: bool = attrs.field(default=True, init=False)


@typing.final
@attrs.frozen
class WGroupTransaction(_TransactionRelatedWType):
    scalar_type: typing.Literal[AVMType.uint64] = attrs.field(default=AVMType.uint64, init=False)

    @classmethod
    def from_type(cls, transaction_type: constants.TransactionType | None) -> "WGroupTransaction":
        name = "group_transaction"
        if transaction_type:
            name = f"{name}_{transaction_type.name}"
        return cls(name=name, transaction_type=transaction_type)


@typing.final
@attrs.frozen
class WInnerTransactionFields(_TransactionRelatedWType):
    scalar_type: None = attrs.field(default=None, init=False)

    @classmethod
    def from_type(
        cls, transaction_type: constants.TransactionType | None
    ) -> "WInnerTransactionFields":
        name = "inner_transaction_fields"
        if transaction_type:
            name = f"{name}_{transaction_type.name}"
        return cls(name=name, transaction_type=transaction_type)


@typing.final
@attrs.frozen
class WInnerTransaction(_TransactionRelatedWType):
    scalar_type: None = attrs.field(default=None, init=False)

    @classmethod
    def from_type(cls, transaction_type: constants.TransactionType | None) -> "WInnerTransaction":
        name = "inner_transaction"
        if transaction_type:
            name = f"{name}_{transaction_type.name}"
        return cls(name=name, transaction_type=transaction_type)


@typing.final
@attrs.frozen(init=False)
class WStructType(WType):
    fields: Mapping[str, WType] = attrs.field(converter=immutabledict)
    scalar_type: None = attrs.field(default=None, init=False)

    def __init__(
        self,
        fields: Mapping[str, WType],
        *,
        name: str,
        immutable: bool,
        source_location: SourceLocation | None,
    ):
        if not fields:
            raise CodeError("struct needs fields", source_location)
        if void_wtype in fields.values():
            raise CodeError("struct should not contain void types", source_location)
        self.__attrs_init__(name=name, fields=fields, immutable=immutable)


@typing.final
@attrs.frozen(init=False)
class WArray(WType):
    element_type: WType
    scalar_type: None = attrs.field(default=None, init=False)

    def __init__(self, element_type: WType, source_location: SourceLocation | None):
        if element_type == void_wtype:
            raise CodeError("array element type cannot be void", source_location)
        name = f"array<{element_type.name}>"
        self.__attrs_init__(name=name, element_type=element_type, immutable=False)


@typing.final
@attrs.frozen(init=False)
class WTuple(WType):
    types: tuple[WType, ...] = attrs.field(validator=[attrs.validators.min_len(1)])
    scalar_type: None = attrs.field(default=None, init=False)
    immutable: bool = attrs.field(default=True, init=False)

    def __init__(self, types: Iterable[WType], source_location: SourceLocation | None):
        types = tuple(types)
        if not types:
            raise CodeError("tuple needs types", source_location)
        if void_wtype in types:
            raise CodeError("tuple should not contain void types", source_location)
        name = f"tuple<{','.join([t.name for t in types])}>"
        self.__attrs_init__(name=name, types=types)


@attrs.frozen(kw_only=True)
class ARC4Type(WType):
    scalar_type: typing.Literal[AVMType.bytes] = attrs.field(default=AVMType.bytes, init=False)
    arc4_name: str = attrs.field(eq=False)  # exclude from equality in case of aliasing
    decode_type: WType | None
    _other_encodeable_types: Collection[WType] = attrs.field(default=())

    @cached_property
    def encodeable_types(self) -> frozenset[WType]:
        if self.decode_type is None:
            return frozenset(self._other_encodeable_types)
        return frozenset([self.decode_type, *self._other_encodeable_types])


arc4_bool_wtype: typing.Final = ARC4Type(
    name="arc4.bool",
    arc4_name="bool",
    immutable=True,
    decode_type=bool_wtype,
)


@typing.final
@attrs.frozen(init=False, kw_only=True)
class ARC4UIntN(ARC4Type):
    immutable: bool = attrs.field(default=True, init=False)
    decode_type: WType
    n: int

    def __init__(
        self,
        n: int,
        source_location: SourceLocation | None,
        *,
        decode_type: WType,
        alias: str | None = None,
    ):
        if not (n % 8 == 0):
            raise CodeError("Bit size must be multiple of 8", source_location)
        if not (8 <= n <= 512):
            raise CodeError("Bit size must be between 8 and 512 inclusive", source_location)
        if decode_type == uint64_wtype:
            if n > 64:
                raise InternalError("TODO", source_location)
        elif decode_type == biguint_wtype:
            pass
        else:
            raise InternalError("TODO", source_location)
        default_arc4_name = f"uint{n}"
        arc4_name = alias or default_arc4_name
        self.__attrs_init__(
            name=f"arc4.{default_arc4_name}",
            arc4_name=arc4_name,
            n=n,
            decode_type=decode_type,
            other_encodeable_types=frozenset({bool_wtype, uint64_wtype, biguint_wtype}),
        )


@typing.final
@attrs.frozen(init=False, kw_only=True)
class ARC4UFixedNxM(ARC4Type):
    n: int
    m: int
    immutable: bool = attrs.field(default=True, init=False)

    def __init__(self, bits: int, precision: int, source_location: SourceLocation | None):
        if not (bits % 8 == 0):
            raise CodeError("Bit size must be multiple of 8", source_location)
        if not (8 <= bits <= 512):
            raise CodeError("Bit size must be between 8 and 512 inclusive", source_location)
        if not (1 <= precision <= 160):
            raise CodeError("Precision must be between 1 and 160 inclusive", source_location)

        arc4_name = f"ufixed{bits}x{precision}"
        self.__attrs_init__(
            name=f"arc4.{arc4_name}",
            arc4_name=arc4_name,
            n=bits,
            m=precision,
            decode_type=None,
        )


@typing.final
@attrs.frozen(init=False, kw_only=True)
class ARC4Tuple(ARC4Type):
    types: tuple[ARC4Type, ...] = attrs.field(validator=[attrs.validators.min_len(1)])

    def __init__(self, types: Iterable[WType], source_location: SourceLocation | None):
        types = tuple(types)
        if not types:
            raise CodeError("ARC4 Tuple cannot be empty", source_location)
        immutable = True
        arc4_types = []
        for typ_idx, typ in enumerate(types):
            if not isinstance(typ, ARC4Type):
                raise CodeError(
                    f"Invalid ARC4 Tuple type:"
                    f" type at index {typ_idx} is not an ARC4 encoded type",
                    source_location,
                )
            arc4_types.append(typ)
            # this seems counterintuitive, but is necessary.
            # despite the overall collection remaining stable, since ARC4 types
            # are encoded as a single value, if items within the tuple can be mutated,
            # then the overall value is also mutable
            immutable = immutable and typ.immutable
        name = f"arc4.tuple<{','.join([t.name for t in types])}>"
        arc4_name = f"({','.join(item.arc4_name for item in arc4_types)})"
        native_type = WTuple(types, source_location)
        self.__attrs_init__(
            name=name,
            arc4_name=arc4_name,
            types=tuple(arc4_types),
            immutable=immutable,
            decode_type=native_type,
        )


@attrs.frozen(kw_only=True)
class ARC4Array(ARC4Type):
    element_type: ARC4Type


@typing.final
@attrs.frozen(init=False)
class ARC4DynamicArray(ARC4Array):
    def __init__(
        self,
        element_type: WType,
        source_location: SourceLocation | None,
        *,
        alias: str | None = None,
        native_type: WType | None = None,
        immutable: bool = False,
    ):
        if not isinstance(element_type, ARC4Type):
            raise CodeError("ARC4 arrays must have ARC4 encoded element type", source_location)
        name = f"arc4.dynamic_array<{element_type.name}>"
        arc4_name = alias or f"{element_type.arc4_name}[]"
        self.__attrs_init__(
            name=name,
            arc4_name=arc4_name,
            element_type=element_type,
            decode_type=native_type,
            immutable=immutable,
        )


@typing.final
@attrs.frozen(kw_only=True, init=False)
class ARC4StaticArray(ARC4Array):
    array_size: int

    def __init__(
        self,
        element_type: WType,
        array_size: int,
        source_location: SourceLocation | None,
        *,
        alias: str | None = None,
        native_type: WType | None = None,
        immutable: bool = False,
    ):
        if not isinstance(element_type, ARC4Type):
            raise CodeError("ARC4 arrays must have ARC4 encoded element type", source_location)
        if array_size < 0:
            raise CodeError("ARC4 static array size must be non-negative", source_location)
        name = f"arc4.static_array<{element_type.name}, {array_size}>"
        arc4_name = alias or f"{element_type.arc4_name}[{array_size}]"
        self.__attrs_init__(
            name=name,
            arc4_name=arc4_name,
            element_type=element_type,
            array_size=array_size,
            decode_type=native_type,
            immutable=immutable,
        )


@typing.final
@attrs.frozen(kw_only=True, init=False)
class ARC4Struct(ARC4Type):
    fields: Mapping[str, ARC4Type] = attrs.field(
        converter=immutabledict, validator=[attrs.validators.min_len(1)]
    )

    @cached_property
    def names(self) -> Sequence[str]:
        return list(self.fields.keys())

    @cached_property
    def types(self) -> Sequence[ARC4Type]:
        return list(self.fields.values())

    def __init__(
        self,
        fields: Mapping[str, WType],
        *,
        name: str,
        immutable: bool,
        source_location: SourceLocation | None,
    ):
        if not fields:
            raise CodeError("arc4.Struct needs at least one element", source_location)
        arc4_fields = {}
        bad_field_names = []
        for field_name, field_wtype in fields.items():
            if not isinstance(field_wtype, ARC4Type):
                bad_field_names.append(field_name)
                continue

            arc4_fields[field_name] = field_wtype
            # this seems counterintuitive, but is necessary.
            # despite the overall collection remaining stable, since ARC4 types
            # are encoded as a single value, if items within a "frozen" struct can be mutated,
            # then the overall value is also mutable
            immutable = immutable and field_wtype.immutable
        if bad_field_names:
            raise CodeError(
                "Invalid ARC4 Struct declaration,"
                f" the following fields are not ARC4 encoded types: {', '.join(bad_field_names)}",
                source_location,
            )

        arc4_name = ARC4Tuple(
            types=arc4_fields.values(), source_location=source_location
        ).arc4_name
        self.__attrs_init__(
            name=name,
            arc4_name=arc4_name,
            fields=arc4_fields,
            immutable=immutable,
            decode_type=None,
        )


arc4_byte_alias: typing.Final = ARC4UIntN(
    n=8,
    alias="byte",
    decode_type=uint64_wtype,
    source_location=None,
)

arc4_string_wtype: typing.Final = ARC4DynamicArray(
    alias="string",
    element_type=arc4_byte_alias,
    native_type=string_wtype,
    immutable=True,
    source_location=None,
)

arc4_address_wtype: typing.Final = ARC4StaticArray(
    alias="address",
    element_type=arc4_byte_alias,
    native_type=account_wtype,
    array_size=32,
    immutable=True,
    source_location=None,
)


def persistable_stack_type(
    wtype: WType, location: SourceLocation
) -> typing.Literal[AVMType.uint64, AVMType.bytes]:
    match _storage_type_or_error(wtype):
        case str(error):
            raise CodeError(error, location=location)
        case result:
            return result


def validate_persistable(wtype: WType, location: SourceLocation) -> bool:
    match _storage_type_or_error(wtype):
        case str(error):
            logger.error(error, location=location)
            return False
        case _:
            return True


def _storage_type_or_error(wtype: WType) -> str | typing.Literal[AVMType.uint64, AVMType.bytes]:
    if wtype.ephemeral:
        return "ephemeral types (such as transaction related types) are not suitable for storage"
    if wtype.scalar_type is None:
        return "type is not suitable for storage"
    return wtype.scalar_type


# TODO: move these validation functions somewhere else
def valid_base32(s: str) -> bool:
    """check if s is a valid base32 encoding string and fits into AVM bytes type"""
    try:
        value = base64.b32decode(s)
    except ValueError:
        return False
    return len(value) <= algo_constants.MAX_BYTES_LENGTH
    # regex from PyTEAL, appears to be RFC-4648
    # ^(?:[A-Z2-7]{8})*(?:([A-Z2-7]{2}([=]{6})?)|([A-Z2-7]{4}([=]{4})?)|([A-Z2-7]{5}([=]{3})?)|([A-Z2-7]{7}([=]{1})?))?  # noqa: E501


def valid_base16(s: str) -> bool:
    try:
        value = base64.b16decode(s)
    except ValueError:
        return False
    return len(value) <= algo_constants.MAX_BYTES_LENGTH


def valid_base64(s: str) -> bool:
    """check if s is a valid base64 encoding string and fits into AVM bytes type"""
    try:
        value = base64.b64decode(s, validate=True)
    except ValueError:
        return False
    return len(value) <= algo_constants.MAX_BYTES_LENGTH
    # regex from PyTEAL, appears to be RFC-4648
    # ^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$


def valid_address(address: str) -> bool:
    """check if address is a valid address with checksum"""
    # Pad address so it's a valid b32 string
    padded_address = address + (6 * "=")
    if not (
        len(address) == algo_constants.ENCODED_ADDRESS_LENGTH and valid_base32(padded_address)
    ):
        return False
    address_bytes = base64.b32decode(padded_address)
    if (
        len(address_bytes)
        != algo_constants.PUBLIC_KEY_HASH_LENGTH + algo_constants.ADDRESS_CHECKSUM_LENGTH
    ):
        return False

    public_key_hash = address_bytes[: algo_constants.PUBLIC_KEY_HASH_LENGTH]
    check_sum = address_bytes[algo_constants.PUBLIC_KEY_HASH_LENGTH :]
    verified_check_sum = sha512_256_hash(public_key_hash)[
        -algo_constants.ADDRESS_CHECKSUM_LENGTH :
    ]
    return check_sum == verified_check_sum


def is_reference_type(wtype: WType) -> bool:
    return wtype in (asset_wtype, account_wtype, application_wtype)


def is_arc4_argument_type(wtype: WType) -> bool:
    return is_reference_type(wtype) or isinstance(wtype, ARC4Type | WGroupTransaction)


def has_arc4_equivalent_type(wtype: WType) -> bool:
    """
    Checks if a non-arc4 encoded type has an arc4 equivalent
    """
    if wtype in (bool_wtype, uint64_wtype, bytes_wtype, biguint_wtype, string_wtype):
        return True

    match wtype:
        case WTuple(types=types):
            return all(
                (has_arc4_equivalent_type(t) or isinstance(t, ARC4Type))
                and not isinstance(t, WTuple)
                for t in types
            )
    return False


def avm_to_arc4_equivalent_type(wtype: WType) -> ARC4Type:
    if wtype is bool_wtype:
        return arc4_bool_wtype
    if wtype is uint64_wtype:
        return ARC4UIntN(64, decode_type=wtype, source_location=None)
    if wtype is biguint_wtype:
        return ARC4UIntN(512, decode_type=wtype, source_location=None)
    if wtype is bytes_wtype:
        return ARC4DynamicArray(
            element_type=arc4_byte_alias, native_type=wtype, source_location=None
        )
    if wtype is string_wtype:
        return arc4_string_wtype
    if isinstance(wtype, WTuple):
        return ARC4Tuple(
            types=(
                t if isinstance(t, ARC4Type) else avm_to_arc4_equivalent_type(t)
                for t in wtype.types
            ),
            source_location=None,
        )
    raise InternalError(f"{wtype} does not have an arc4 equivalent type")
