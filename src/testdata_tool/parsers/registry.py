from __future__ import annotations

from .tabular import DelimitedParser, TabularParser, UnsupportedParser


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers = {
            "tabular": TabularParser(),
            "delimited": DelimitedParser(),
            "proprietary_t12": UnsupportedParser("proprietary_t12"),
            "unsupported": UnsupportedParser("unsupported"),
        }

    def get(self, parser_id: str | None):
        if not parser_id:
            return UnsupportedParser("未配置解析器")
        return self._parsers.get(parser_id, UnsupportedParser(parser_id))

    def supports(self, parser_id: str | None, path) -> bool:
        return self.get(parser_id).probe(path)

