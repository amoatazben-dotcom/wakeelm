from abc import ABC, abstractmethod


class AIProviderAdapter(ABC):
    @abstractmethod
    async def discover_models(self): ...
    @abstractmethod
    async def create_chat_completion(self, model, text, max_tokens=256): ...
    async def health_check(self):
        return await self.discover_models()

    async def test_model(self, model):
        return await self.create_chat_completion(model, "Reply with OK.", max_tokens=4)

    async def stream_chat_completion(self, *args, **kwargs):
        raise NotImplementedError("Streaming is reserved for a later stage")
