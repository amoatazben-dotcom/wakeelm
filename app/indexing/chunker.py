import hashlib


def token_estimate(text):
    # UTF-8 bytes provide a deliberately conservative multilingual bound.
    return max(1, (len(text.encode("utf-8")) + 2) // 3)


class Chunker:
    def chunks(self, text, symbols, max_tokens=700):
        lines = text.splitlines(keepends=True)
        boundaries = {0, len(lines)}
        for symbol in symbols:
            if symbol["symbol_type"] in {"class", "function", "method", "test_function"}:
                boundaries.update(
                    {max(0, symbol["start_line"] - 1), min(len(lines), symbol["end_line"])}
                )
        edges = sorted(boundaries)
        output = []
        for begin, end in zip(edges, edges[1:]):
            current = ""
            start = begin
            for index in range(begin, end):
                line = lines[index]
                if current and token_estimate(current + line) > max_tokens:
                    output.append(self._chunk(current, start + 1, index))
                    current = ""
                    start = index
                # A single very long line is bounded, with explicit truncation provenance.
                current += line[: max_tokens * 2]
            if current:
                output.append(self._chunk(current, start + 1, end))
        return output

    def _chunk(self, text, start, end):
        return {
            "content": text,
            "start_line": start,
            "end_line": end,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "token_estimate": token_estimate(text),
        }
