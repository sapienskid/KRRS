"""Define the configurable parameters for the agent."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Annotated, Any, Literal, Optional, Type, TypeVar

from langchain_core.runnables import RunnableConfig, ensure_config

from retrieval_graph import prompts
import os


@dataclass(kw_only=True)
class IndexConfiguration:
    """Configuration class for indexing and retrieval operations.

    This class defines the parameters needed for configuring the indexing and
    retrieval processes, including user identification, embedding model selection,
    retriever provider choice, and search parameters.
    """

    user_id: str = field(
        default_factory=lambda: os.getenv("USER_ID", ""),
        metadata={"description": "Unique identifier for the user."}
    )
    
    elasticsearch_host: str = field(
        default_factory=lambda: os.getenv("ELASTICSEARCH_HOST", "localhost"),
        metadata={"description": "Hostname or IP address of the Elasticsearch server."}
    )
    
    elasticsearch_port: int = field(
        default_factory=lambda: int(os.getenv("ELASTICSEARCH_PORT", "9200")),
        metadata={"description": "Port number for the Elasticsearch server."}
    )

    embedding_model: Annotated[
        str,
        {"__template_metadata__": {"kind": "embeddings"}},
    ] = field(
        default="google/text-embedding-004",
        metadata={
            "description": "Name of the embedding model to use. Must be a valid embedding model name."
        },
    )

    retriever_provider: Annotated[
        Literal["elastic-local"],
        {"__template_metadata__": {"kind": "retriever"}},
    ] = field(
        default="elastic-local",
        metadata={
            "description": "The vector store provider to use for retrieval. Options are 'elastic-local'."
        },
    )

    search_kwargs: dict[str, Any] = field(
        default_factory=dict,
        metadata={
            "description": "Additional keyword arguments to pass to the search function of the retriever."
        },
    )

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.user_id or self.user_id == "default_user":
            raise ValueError("Please provide a valid user_id in the configuration.")
        
        # Ensure embedding_model is not None or empty
        if not self.embedding_model:
            self.embedding_model = "google/text-embedding-004"
        
        # Fix Google embedding model names to the correct format
        if self.embedding_model:
            if self.embedding_model.startswith("google/") and not self.embedding_model.startswith("google/models/"):
                if "text-embedding-005" in self.embedding_model:
                    # text-embedding-005 is not available, use text-embedding-004 instead
                    self.embedding_model = "google/models/text-embedding-004"
                elif "text-embedding-004" in self.embedding_model:
                    self.embedding_model = "google/models/text-embedding-004"
                else:
                    # For other Google models, add the models/ prefix
                    model_name = self.embedding_model.split("/", 1)[1]
                    self.embedding_model = f"google/models/{model_name}"
            elif "/" not in self.embedding_model:
                # If no provider specified, assume it's a Google model and add the proper prefix
                self.embedding_model = f"google/models/{self.embedding_model}"

    @classmethod
    def from_runnable_config(
        cls: Type[T], config: Optional[RunnableConfig] = None
    ) -> T:
        """Create an IndexConfiguration instance from a RunnableConfig object.

        Args:
            cls (Type[T]): The class itself.
            config (Optional[RunnableConfig]): The configuration object to use.

        Returns:
            T: An instance of IndexConfiguration with the specified configuration.
        """
        config = ensure_config(config)
        configurable = config.get("configurable") or {}
        _fields = {f.name for f in fields(cls) if f.init}
        return cls(**{k: v for k, v in configurable.items() if k in _fields})


T = TypeVar("T", bound=IndexConfiguration)


@dataclass(kw_only=True)
class Configuration(IndexConfiguration):
    """The configuration for the agent."""

    response_system_prompt: str = field(
        default=prompts.RESPONSE_SYSTEM_PROMPT,
        metadata={"description": "The system prompt used for generating responses."},
    )

    response_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="anthropic/claude-3-5-sonnet-20240620",
        metadata={
            "description": "The language model used for generating responses. Should be in the form: provider/model-name."
        },
    )

    query_system_prompt: str = field(
        default=prompts.QUERY_SYSTEM_PROMPT,
        metadata={
            "description": "The system prompt used for processing and refining queries."
        },
    )

    query_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="anthropic/claude-3-haiku-20240307",
        metadata={
            "description": "The language model used for processing and refining queries. Should be in the form: provider/model-name."
        },
    )
