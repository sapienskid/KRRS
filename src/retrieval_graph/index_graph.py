"""This "graph" simply exposes an endpoint for a user to upload docs to be indexed."""

from typing import Sequence

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph

from retrieval_graph import retrieval
from retrieval_graph.configuration import IndexConfiguration
from retrieval_graph.state import IndexState
from retrieval_graph.utils import create_documents_from_urls


def ensure_docs_have_user_id(
    docs: Sequence[Document], config: RunnableConfig
) -> list[Document]:
    """Ensure that all documents have a user_id in their metadata.

        docs (Sequence[Document]): A sequence of Document objects to process.
        config (RunnableConfig): A configuration object containing the user_id.

    Returns:
        list[Document]: A new list of Document objects with updated metadata.
    """
    user_id = config["configurable"]["user_id"]
    return [
        Document(
            page_content=doc.page_content, metadata={**doc.metadata, "user_id": user_id}
        )
        for doc in docs
    ]


async def index_docs(
    state: IndexState, *, config: RunnableConfig | None
) -> dict[str, str]:
    """Asynchronously index documents in the given state using the configured retriever.

    This function takes the documents from the state, ensures they have a user ID,
    adds them to the retriever's index, and then signals for the documents to be
    deleted from the state.

    Args:
        state (IndexState): The current state containing documents and retriever.
        config (Optional[RunnableConfig]): Configuration for the indexing process.r
    """
    if not config:
        raise ValueError("Configuration required to run index_docs.")
    with retrieval.make_retriever(config) as retriever:
        stamped_docs = ensure_docs_have_user_id(state.docs, config)

        await retriever.aadd_documents(stamped_docs)
    return {"docs": "delete"}


async def index_urls(
    state: IndexState, *, config: RunnableConfig | None
) -> dict[str, str]:
    """Index documents from URLs (PDFs and web pages).

    This function processes URLs to extract content and index the resulting documents.

    Args:
        state (IndexState): The current state containing URLs to process.
        config (Optional[RunnableConfig]): Configuration for the indexing process.
    """
    if not config:
        raise ValueError("Configuration required to run index_urls.")

    # Extract URLs from state - assuming they're passed as docs with URL content
    urls = []
    for doc in state.docs:
        if doc.page_content.startswith(("http://", "https://")):
            urls.append(doc.page_content.strip())

    if urls:
        # Process URLs to create documents
        processed_docs = create_documents_from_urls(urls)

        if processed_docs:
            with retrieval.make_retriever(config) as retriever:
                stamped_docs = ensure_docs_have_user_id(processed_docs, config)
                await retriever.aadd_documents(stamped_docs)

    return {"docs": "delete"}


# Define a new graph


builder = StateGraph(IndexState, config_schema=IndexConfiguration)
builder.add_node("index_docs", index_docs)
builder.add_node("index_urls", index_urls)
builder.add_edge("__start__", "index_docs")
builder.add_edge("index_docs", "index_urls")
# Finally, we compile it!
# This compiles it into a graph you can invoke and deploy.
graph = builder.compile()
graph.name = "IndexGraph"
