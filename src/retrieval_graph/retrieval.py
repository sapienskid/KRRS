"""Manage the configuration of various retrievers.

This module provides functionality to create and manage retrievers for different
vector store backends, specifically Elasticsearch, Pinecone, and MongoDB.

The retrievers support filtering results by user_id to ensure data isolation between users.
"""

import os
import asyncio
from contextlib import contextmanager
from typing import Generator

from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnableConfig
from langchain_core.vectorstores import VectorStoreRetriever

from retrieval_graph.configuration import Configuration, IndexConfiguration

## Encoder constructors


def make_text_encoder(model: str) -> Embeddings:
    """Connect to the configured text encoder."""
    if not model:
        raise ValueError("Embedding model cannot be empty or None")
    
    # Handle cases where model string doesn't contain a provider prefix
    if "/" not in model:
        # Default to google provider for models without a provider prefix
        provider = "google"
        model_name = model
    else:
        provider, model_name = model.split("/", maxsplit=1)
    
    match provider:
        case "google":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            return GoogleGenerativeAIEmbeddings(model=model_name)
        case _:
            raise ValueError(f"Unsupported embedding provider: {provider}")


## Retriever constructors


async def _create_async_elastic_retriever(
    configuration: IndexConfiguration, embedding_model: Embeddings
) -> VectorStoreRetriever:
    """Internal async function to create Elasticsearch retriever."""
    from langchain_elasticsearch import AsyncElasticsearchStore
    from elasticsearch import AsyncElasticsearch

    connection_options = {}
    if configuration.retriever_provider == "elastic-local":
        connection_options = {
            "basic_auth": (
                os.environ["ELASTICSEARCH_USER"], 
                os.environ["ELASTICSEARCH_PASSWORD"]
            ),
        }
    else:
        connection_options = {"api_key": os.environ["ELASTICSEARCH_API_KEY"]}

    # Create async Elasticsearch client
    es_client = AsyncElasticsearch(
        hosts=[os.environ["ELASTICSEARCH_URL"]],
        **connection_options
    )

    # Create AsyncElasticsearchStore
    vstore = AsyncElasticsearchStore(
        es_connection=es_client,
        index_name="langchain_index",
        embedding=embedding_model,
    )

    search_kwargs = configuration.search_kwargs.copy()

    # Add user_id filter for data isolation
    search_filter = search_kwargs.setdefault("filter", [])
    search_filter.append({"term": {"metadata.user_id": configuration.user_id}})
    
    # Set default k to limit retrieved documents (default to 1 as specified)
    if "k" not in search_kwargs:
        search_kwargs["k"] = 1
    
    return vstore.as_retriever(search_kwargs=search_kwargs)


@contextmanager
def make_elastic_retriever(
    configuration: IndexConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Configure this agent to connect to a specific elastic index using async operations."""
    
    # Run the async creation in a thread to avoid blocking
    async def create_retriever():
        return await _create_async_elastic_retriever(configuration, embedding_model)
    
    # Use asyncio.to_thread to run the async operation without blocking
    try:
        # Get or create event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an async context, we need to use a different approach
            # This creates the retriever using the async method but wraps it for sync use
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, create_retriever())
                retriever = future.result(timeout=30)
        else:
            retriever = loop.run_until_complete(create_retriever())
    except RuntimeError:
        # Fallback: create a new event loop
        retriever = asyncio.run(create_retriever())
    
    try:
        yield retriever
    finally:
        # Clean up the retriever's connection if it has one
        if hasattr(retriever.vectorstore, 'client') and hasattr(retriever.vectorstore.client, 'close'):
            try:
                # Try to close the client properly
                if asyncio.iscoroutinefunction(retriever.vectorstore.client.close):
                    try:
                        loop = asyncio.get_event_loop()
                        if not loop.is_closed():
                            loop.run_until_complete(retriever.vectorstore.client.close())
                    except RuntimeError:
                        asyncio.run(retriever.vectorstore.client.close())
                else:
                    retriever.vectorstore.client.close()
            except Exception:
                # Ignore cleanup errors
                pass


@contextmanager
def make_retriever(
    config: RunnableConfig,
) -> Generator[VectorStoreRetriever, None, None]:
    """Create a retriever for the agent, based on the current configuration."""
    configuration = IndexConfiguration.from_runnable_config(config)
    embedding_model = make_text_encoder(configuration.embedding_model)
    user_id = configuration.user_id
    if not user_id:
        raise ValueError("Please provide a valid user_id in the configuration.")
    
    match configuration.retriever_provider:
        case "elastic-local":
            with make_elastic_retriever(configuration, embedding_model) as retriever:
                yield retriever
        case _:
            raise ValueError(
                "Unrecognized retriever_provider in configuration. "
                f"Expected one of: {', '.join(Configuration.__annotations__['retriever_provider'].__args__)}\n"
                f"Got: {configuration.retriever_provider}"
            )