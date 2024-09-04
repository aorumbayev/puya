import attrs

from puya.context import CompileContext
from puya.models import TemplateValue
from puya.ussemble.debug import Event


@attrs.frozen(kw_only=True)
class AssembleContext(CompileContext):
    template_variables: dict[str, TemplateValue] = attrs.field(factory=dict)
    events: dict[int, Event] = attrs.field(factory=dict)
