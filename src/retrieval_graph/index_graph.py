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
    """Index documents from URLs (PDFs and web pages) with content validation.

    This function processes URLs to extract content, validates that actual content
    was extracted (not just the URL), and provides clear error messages for failures.

    Args:
        state (IndexState): The current state containing URLs to process.
        config (Optional[RunnableConfig]): Configuration for the indexing process.
    """
    if not config:
        raise ValueError("Configuration required to run index_urls.")

    # Extract URLs from state
    urls = []
    for doc in state.docs:
        if doc.page_content.startswith(("http://", "https://")):
            urls.append(doc.page_content.strip())

    if urls:
        # Process URLs to create documents with content validation (now awaited)
        processed_docs = await create_documents_from_urls(urls)
        
        # Validate that documents contain actual content, not just URLs or errors
        valid_docs = []
        failed_urls = []
        
        for i, doc in enumerate(processed_docs):
            original_url = urls[i] if i < len(urls) else "Unknown URL"
            
            # Check if document contains meaningful content
            content = doc.page_content.strip()
            extraction_success = doc.metadata.get("extraction_success", False)
            
            # More robust validation
            if (not extraction_success or 
                content == original_url or 
                content.startswith(("Failed", "Error", "Document processing dependencies")) or
                len(content) < 200):  # Increased threshold for meaningful content
                failed_urls.append({
                    "url": original_url,
                    "error": content if content.startswith(("Failed", "Error")) else "Insufficient content extracted"
                })
            else:
                valid_docs.append(doc)
        
        # Index valid documents
        if valid_docs:
            with retrieval.make_retriever(config) as retriever:
                stamped_docs = ensure_docs_have_user_id(valid_docs, config)
                await retriever.aadd_documents(stamped_docs)
                print(f"Successfully indexed {len(valid_docs)} documents from URLs.")
        
        # Provide detailed error reporting
        if failed_urls:
            error_details = []
            for failed in failed_urls[:3]:  # Show first 3 failures
                error_details.append(f"  - {failed['url']}: {failed['error']}")
            
            error_msg = (f"Failed to extract content from {len(failed_urls)} URL(s):\n" + 
                        "\n".join(error_details) + 
                        ("..." if len(failed_urls) > 3 else "") +
                        "\n\nPlease verify URLs are accessible and contain extractable content, or upload document text manually.")
            print(f"URL Processing Error: {error_msg}")
            
            # If all URLs failed, raise an exception to notify the user
            if not valid_docs:
                raise ValueError(f"Could not extract content from any of the provided URLs. {error_msg}")

    return {"docs": "delete"}
# Define a new graph


builder = StateGraph(IndexState, config_schema=IndexConfiguration)
builder.add_node("index_docs", index_docs)
builder.add_node("index_urls", index_urls)
builder.add_edge("__start__", "index_urls")  # Process URLs first
builder.add_edge("index_urls", "index_docs")  # Then process any remaining docs
# Finally, we compile it!
# This compiles it into a graph you can invoke and deploy.
graph = builder.compile()
graph.name = "IndexGraph"
