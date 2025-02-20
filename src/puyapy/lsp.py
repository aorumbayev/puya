import argparse
import sys
import typing
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

import attrs
from lsprotocol import types
from lsprotocol.types import DiagnosticSeverity
from pygls.lsp.server import LanguageServer

from puya.compile import awst_to_teal
from puya.errors import log_exceptions
from puya.log import Log, LoggingContext, LogLevel, logging_context
from puya.parse import SourceLocation
from puyapy.awst_build.main import transform_ast
from puyapy.compile import parse_with_mypy
from puyapy.options import PuyaPyOptions
from puyapy.parse import ParseResult
from puyapy.utils import determine_out_dir

_NAME = "puyapy-lsp"
_VERSION = version("puyapy")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog=_NAME,
        description="puyapy language server, defaults to listening on localhost:8888",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s ({_VERSION})")
    parser.add_argument("--stdio", action="store_true", help="start a stdio server")
    parser.add_argument("--host", default="localhost", help="bind to this address")
    parser.add_argument("--socket", type=int, default=8888, help="bind to this port")

    arguments = parser.parse_args(sys.argv[1:])
    if arguments.stdio:
        server.start_io()
    else:
        server.start_tcp(arguments.host, arguments.socket)


class PuyaPyLanguageServer(LanguageServer):
    def __init__(self, name: str, version: str) -> None:
        super().__init__(name, version=version)
        self.diagnostics = dict[str, tuple[int | None, list[types.Diagnostic]]]()
        self.analysis_prefix: Path | None = None

    def parse_all(self) -> None:
        # examine all files from workspace root
        src_path = Path(self.workspace.root_path)
        # get all sources tracked by the workspace
        sources = {Path(d.path): d.source for d in self.workspace.text_documents.values()}
        options = PuyaPyOptions(
            log_level=LogLevel.warning,
            paths=[src_path],
            sources=sources,
            prefix=self.analysis_prefix,
        )
        logs = self._parse_and_log(options)

        # need to include existing documents in diagnostics case all errors are cleared
        diagnostics: dict[str, tuple[int | None, list[types.Diagnostic]]] = {
            uri: (self.workspace.get_text_document(uri).version, []) for uri in self.diagnostics
        }
        for log in logs:
            if log.location and log.location.file:
                uri = log.location.file.as_uri()
                doc = self.workspace.get_text_document(uri)
                version_diags = diagnostics.setdefault(uri, (doc.version, []))[1]
                range_ = self._resolve_location(log.location)
                version_diags.append(
                    _diag(
                        log.message,
                        log.level,
                        range_,
                        data=self._get_source_code_data(uri, range_),
                    )
                )
        self.diagnostics = diagnostics

    def _resolve_location(self, loc: SourceLocation) -> types.Range:
        if loc and loc.file:
            line = loc.line - 1
            column = loc.column or 0
            end_line = loc.end_line - 1
            end_column = loc.end_column
            if end_column is None:
                document = self.workspace.get_text_document(loc.file.as_uri())
                end_column = len(document.lines[end_line])
            return types.Range(
                start=types.Position(line=line, character=column),
                end=types.Position(line=end_line, character=end_column),
            )
        else:
            zero = types.Position(line=0, character=0)
            return types.Range(start=zero, end=zero)

    def _get_source_code_data(self, uri: str, range_: types.Range) -> object:
        document = self.workspace.get_text_document(uri)
        lines = document.lines[range_.start.line : range_.end.line + 1]
        # do end_column first in case line == end_line
        lines[-1] = lines[-1][: range_.end.character]
        lines[0] = lines[0][range_.start.character :]
        source_code = "\n".join(lines)
        return {"source_code": source_code}

    def _filter_parse_results(
        self, log_ctx: LoggingContext, parse_result: ParseResult
    ) -> ParseResult:
        files_with_errors = {
            log.location.file
            for log in log_ctx.logs
            if log.level == LogLevel.error and log.location and log.location.file
        }
        return attrs.evolve(
            parse_result,
            ordered_modules={
                p: m
                for p, m in parse_result.ordered_modules.items()
                if m.path not in files_with_errors
            },
        )

    def _parse_and_log(self, puyapy_options: PuyaPyOptions) -> Sequence[Log]:
        with logging_context() as log_ctx, log_exceptions():
            parse_result = parse_with_mypy(
                puyapy_options.paths, puyapy_options.sources, prefix=puyapy_options.prefix
            )
            log_ctx.sources_by_path = parse_result.sources_by_path
            if log_ctx.num_errors:
                # if there were type checking errors
                # attempt to continue with any modules that don't have errors
                parse_result = self._filter_parse_results(log_ctx, parse_result)
            awst, compilation_targets = transform_ast(parse_result)
            # if no errors, then attempt to lower further
            if not log_ctx.num_errors:
                awst_lookup = {n.id: n for n in awst}
                compilation_set = {
                    target_id: determine_out_dir(loc.file.parent, puyapy_options)
                    for target_id, loc in (
                        (t, awst_lookup[t].source_location) for t in compilation_targets
                    )
                    if loc.file
                }
                awst_to_teal(
                    log_ctx, puyapy_options, compilation_set, parse_result.sources_by_path, awst
                )
        return log_ctx.logs


server = PuyaPyLanguageServer(_NAME, version=_VERSION)


class _HasTextDocument(typing.Protocol):
    @property
    def text_document(self) -> types.VersionedTextDocumentIdentifier: ...


def _refresh_diagnostics(ls: PuyaPyLanguageServer, _params: _HasTextDocument) -> None:
    """Refresh all diagnostics when a document changes"""
    ls.parse_all()

    # currently publishes for all documents, ideally only publishes for documents that have changes
    for uri, (doc_version, diagnostics) in ls.diagnostics.items():
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(
                uri=uri,
                version=doc_version,
                diagnostics=diagnostics,
            )
        )


@server.feature(types.INITIALIZE)
def _initialization(ls: PuyaPyLanguageServer, params: types.InitializeParams) -> None:
    options = params.initialization_options
    if options and isinstance(options, dict):
        analysis_prefix = options.get("analysisPrefix")
    else:
        analysis_prefix = ""
    if not analysis_prefix:
        analysis_prefix = sys.prefix
        ls.window_log_message(
            types.LogMessageParams(
                type=types.MessageType.Warning,
                message=f"No analysis prefix provided, using {analysis_prefix}",
            )
        )
    ls.analysis_prefix = Path(analysis_prefix)


@server.feature(
    types.TEXT_DOCUMENT_CODE_ACTION,
    types.CodeActionOptions(code_action_kinds=[types.CodeActionKind.QuickFix]),
)
def code_actions(
    ls: PuyaPyLanguageServer, params: types.CodeActionParams
) -> list[types.CodeAction]:
    items = []
    document_uri = params.text_document.uri
    try:
        _, diagnostics = ls.diagnostics[document_uri]
    except KeyError:
        diagnostics = []
    for diag in diagnostics:
        if diag.severity in (DiagnosticSeverity.Warning, DiagnosticSeverity.Error):
            # POC - fix an int
            if diag.message == "a Python literal is not valid at this location" and isinstance(
                diag.data, dict
            ):
                source_code = diag.data.get("source_code", "")
                # TODO: resolve algopy.UInt64 to correct alias in document
                #       fall back to fully qualified type name if unknown
                uint64_symbol = "UInt64"
                fix = types.TextEdit(
                    range=diag.range,
                    new_text=f"{uint64_symbol}({source_code})",
                )
                action = types.CodeAction(
                    title="Use algopy.UInt64",
                    kind=types.CodeActionKind.QuickFix,
                    edit=types.WorkspaceEdit(changes={document_uri: [fix]}),
                )
                items.append(action)
            else:
                pass
    return items


server.feature(types.TEXT_DOCUMENT_DID_SAVE)(_refresh_diagnostics)
server.feature(types.TEXT_DOCUMENT_DID_OPEN)(_refresh_diagnostics)
server.feature(types.TEXT_DOCUMENT_DID_CHANGE)(_refresh_diagnostics)


def _diag(
    message: str,
    level: LogLevel,
    range_: types.Range,
    data: object = None,
) -> types.Diagnostic:
    return types.Diagnostic(
        message=message,
        severity=_map_severity(level),
        range=range_,
        source=_NAME,
        data=data,
    )


def _map_severity(log_level: LogLevel) -> DiagnosticSeverity:
    if log_level == LogLevel.error:
        return DiagnosticSeverity.Error
    if log_level == LogLevel.warning:
        return DiagnosticSeverity.Warning
    return DiagnosticSeverity.Information


if __name__ == "__main__":
    main()
