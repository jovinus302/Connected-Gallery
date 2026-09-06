from typing import Protocol, Any
from connected_gallery.domain.models import RunRequest


class ModelGateway(Protocol):
    async def invoke(self, messages: list, tool_schemas: list[dict]) -> Any: ...


class AgentRunner(Protocol):
    async def execute(self, run_id: str, request: RunRequest) -> dict: ...


class EmbeddingProvider(Protocol):
    def image(self, image: Any) -> tuple[str, Any]: ...
    def text(
        self, text: str, visual: bool = False, query: bool = True
    ) -> tuple[str, Any]: ...


class PhotoRepository(Protocol):
    def photo(self, photo_id: str) -> Any: ...
    def photos(self, year: int | None = None) -> list: ...


class SearchIndex(Protocol):
    def search(
        self, space: str, query: Any, allowed: set[str], limit: int = 20
    ) -> list: ...


class VisionTools(Protocol):
    def ocr(self, image: Any) -> dict: ...
    def ground(self, image: Any, query: str) -> dict: ...
    def faces(self, image: Any) -> dict: ...


class ArtifactStore(Protocol):
    def read_image(self, photo_id: str, box: Any = None) -> Any: ...
