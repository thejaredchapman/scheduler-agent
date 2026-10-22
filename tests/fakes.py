"""A scripted stand-in for the Anthropic client, so loop tests cost nothing."""
from types import SimpleNamespace


def tool_use(name, input, id="t1"):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def text(words):
    return SimpleNamespace(type="text", text=words)


def response(*blocks, input_tokens=10, output_tokens=5):
    return SimpleNamespace(content=list(blocks), stop_reason="tool_use",
                           usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


class FakeClient:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        # Record a snapshot: the loop keeps appending to the same messages list.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
