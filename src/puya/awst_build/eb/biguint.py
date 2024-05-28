from __future__ import annotations

import typing

import attrs
import mypy.nodes

from puya import log
from puya.awst import wtypes
from puya.awst.nodes import (
    BigUIntAugmentedAssignment,
    BigUIntBinaryOperation,
    BigUIntBinaryOperator,
    BigUIntConstant,
    Expression,
    NumericComparison,
    NumericComparisonExpression,
    Statement,
)
from puya.awst_build import intrinsic_factory, pytypes
from puya.awst_build.eb._base import (
    NotIterableInstanceExpressionBuilder,
)
from puya.awst_build.eb._bytes_backed import (
    BytesBackedInstanceExpressionBuilder,
    BytesBackedTypeBuilder,
)
from puya.awst_build.eb.bool import BoolExpressionBuilder
from puya.awst_build.eb.interface import (
    BuilderBinaryOp,
    BuilderComparisonOp,
    BuilderUnaryOp,
    InstanceBuilder,
    LiteralBuilder,
    LiteralConverter,
    NodeBuilder,
)
from puya.errors import CodeError

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    import mypy.types

    from puya.parse import SourceLocation

logger = log.get_logger(__name__)


class BigUIntTypeBuilder(BytesBackedTypeBuilder, LiteralConverter):
    def __init__(self, location: SourceLocation):
        super().__init__(pytypes.BigUIntType, location)

    @typing.override
    @property
    def convertable_literal_types(self) -> Collection[pytypes.PyType]:
        return (pytypes.IntLiteralType,)

    @typing.override
    def convert_literal(
        self, literal: LiteralBuilder, location: SourceLocation
    ) -> InstanceBuilder:
        match literal.value:
            case int(int_value):
                expr = BigUIntConstant(value=int(int_value), source_location=location)
                return BigUIntExpressionBuilder(expr)
        raise CodeError(f"can't covert literal {literal.value!r} to {self.produces()}", location)

    @typing.override
    def call(
        self,
        args: Sequence[NodeBuilder],
        arg_kinds: list[mypy.nodes.ArgKind],
        arg_names: list[str | None],
        location: SourceLocation,
    ) -> InstanceBuilder:
        match args:
            case []:
                value: Expression = BigUIntConstant(value=0, source_location=location)
            case [LiteralBuilder(value=int(int_value))]:
                value = BigUIntConstant(value=int_value, source_location=location)
            case [InstanceBuilder(pytype=pytypes.UInt64Type) as eb]:
                value = _uint64_to_biguint(eb, location)
            case _:
                logger.error("Invalid/unhandled arguments", location=location)
                # dummy value to continue with
                value = BigUIntConstant(value=0, source_location=location)
        return BigUIntExpressionBuilder(value)


class BigUIntExpressionBuilder(
    NotIterableInstanceExpressionBuilder, BytesBackedInstanceExpressionBuilder
):
    def __init__(self, expr: Expression):
        super().__init__(pytypes.BigUIntType, expr)

    def bool_eval(self, location: SourceLocation, *, negate: bool = False) -> InstanceBuilder:
        cmp_expr = NumericComparisonExpression(
            lhs=self.resolve(),
            operator=NumericComparison.eq if negate else NumericComparison.ne,
            # TODO: does this source location make sense?
            rhs=BigUIntConstant(value=0, source_location=location),
            source_location=location,
        )
        return BoolExpressionBuilder(cmp_expr)

    def unary_op(self, op: BuilderUnaryOp, location: SourceLocation) -> InstanceBuilder:
        if op == BuilderUnaryOp.positive:
            # unary + is allowed, but for the current types it has no real impact
            # so just expand the existing expression to include the unary operator
            return BigUIntExpressionBuilder(attrs.evolve(self.resolve(), source_location=location))
        return super().unary_op(op, location)

    def compare(
        self, other: InstanceBuilder, op: BuilderComparisonOp, location: SourceLocation
    ) -> InstanceBuilder:
        other = other.resolve_literal(converter=BigUIntTypeBuilder(other.source_location))
        if other.pytype == self.pytype:
            other_expr = other.resolve()
        elif other.pytype == pytypes.UInt64Type:
            other_expr = _uint64_to_biguint(other, location)
        else:
            return NotImplemented
        cmp_expr = NumericComparisonExpression(
            source_location=location,
            lhs=self.resolve(),
            operator=NumericComparison(op.value),
            rhs=other_expr,
        )
        return BoolExpressionBuilder(cmp_expr)

    def binary_op(
        self,
        other: InstanceBuilder,
        op: BuilderBinaryOp,
        location: SourceLocation,
        *,
        reverse: bool,
    ) -> InstanceBuilder:
        other = other.resolve_literal(converter=BigUIntTypeBuilder(other.source_location))
        if other.pytype == self.pytype:
            other_expr = other.resolve()
        elif other.pytype == pytypes.UInt64Type:
            other_expr = _uint64_to_biguint(other, location)
        else:
            return NotImplemented
        lhs = self.resolve()
        rhs = other_expr
        if reverse:
            (lhs, rhs) = (rhs, lhs)
        biguint_op = _translate_biguint_math_operator(op, location)
        bin_op_expr = BigUIntBinaryOperation(
            source_location=location, left=lhs, op=biguint_op, right=rhs
        )
        return BigUIntExpressionBuilder(bin_op_expr)

    def augmented_assignment(
        self, op: BuilderBinaryOp, rhs: InstanceBuilder, location: SourceLocation
    ) -> Statement:
        rhs = rhs.resolve_literal(converter=BigUIntTypeBuilder(rhs.source_location))
        if rhs.pytype == self.pytype:
            value = rhs.resolve()
        elif rhs.pytype == pytypes.UInt64Type:
            value = _uint64_to_biguint(rhs, location)
        else:
            raise CodeError(
                f"Invalid operand type {rhs.pytype} for {op.value}= with {self.pytype}", location
            )
        target = self.resolve_lvalue()
        biguint_op = _translate_biguint_math_operator(op, location)
        return BigUIntAugmentedAssignment(
            source_location=location,
            target=target,
            value=value,
            op=biguint_op,
        )


def _translate_biguint_math_operator(
    operator: BuilderBinaryOp, loc: SourceLocation
) -> BigUIntBinaryOperator:
    if operator is BuilderBinaryOp.div:
        logger.error(
            (
                "To maintain semantic compatibility with Python, "
                "only the truncating division operator (//) is supported "
            ),
            location=loc,
        )
        # continue traversing code to generate any further errors
        operator = BuilderBinaryOp.floor_div
    try:
        return BigUIntBinaryOperator(operator.value)
    except ValueError as ex:
        raise CodeError(f"Unsupported BigUInt math operator {operator.value!r}", loc) from ex


def _uint64_to_biguint(arg_in: InstanceBuilder, location: SourceLocation) -> Expression:
    return intrinsic_factory.itob_as(arg_in.resolve(), wtypes.biguint_wtype, location)
