from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from backend.infrastructure.ai.langchain_adapter import LangChainLLMClient, LLMTrace


SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class StructuredPromptChain(Generic[SchemaT]):
    stage_name: str
    schema: type[SchemaT]
    system_prompt: str
    prompt_template: str
    prompt_version: str = "v1"

    def render_prompt(self, values: dict[str, Any]) -> str:
        return self.prompt_template.format(**values)

    def invoke(
        self,
        *,
        client: LangChainLLMClient,
        values: dict[str, Any],
        data_urls: list[str] | None = None,
    ) -> tuple[SchemaT, LLMTrace]:
        return client.invoke_structured(
            stage_name=self.stage_name,
            schema=self.schema,
            system_prompt=self.system_prompt,
            prompt=self.render_prompt(values),
            data_urls=data_urls or [],
            prompt_version=self.prompt_version,
        )


@dataclass(frozen=True)
class TextPromptChain:
    stage_name: str
    system_prompt: str
    prompt_template: str
    prompt_version: str = "v1"

    def render_prompt(self, values: dict[str, Any]) -> str:
        return self.prompt_template.format(**values)

    def invoke(
        self,
        *,
        client: LangChainLLMClient,
        values: dict[str, Any],
        data_urls: list[str] | None = None,
    ) -> tuple[str, LLMTrace]:
        return client.invoke_text(
            stage_name=self.stage_name,
            system_prompt=self.system_prompt,
            prompt=self.render_prompt(values),
            data_urls=data_urls or [],
            prompt_version=self.prompt_version,
        )
