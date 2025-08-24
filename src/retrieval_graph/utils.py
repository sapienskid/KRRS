"""Utility functions for the retrieval graph.

This module contains utility functions for handling messages, documents,
and other common operations in project.

Functions:
    get_message_text: Extract text content from various message formats.
    format_docs: Convert documents to an xml-formatted string with content limits.
    estimate_tokens: Estimate token count for text (rough approximation).
    truncate_to_token_limit: Truncate text to stay within token limits.
"""

import logging
from typing import List

from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage

# Optional imports for document processing
try:
    import asyncio
    import io
    from urllib.parse import urlparse

    import aiohttp
    import PyPDF2

    DOCUMENT_PROCESSING_AVAILABLE = True
except ImportError:
    DOCUMENT_PROCESSING_AVAILABLE = False


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string.
    
    This is a rough approximation: 1 token ≈ 4 characters for English text.
    
    Args:
        text (str): The text to estimate tokens for.
        
    Returns:
        int: Estimated number of tokens.
    """
    if not text:
        return 0
    return len(text) // 4


def truncate_to_token_limit(text: str, max_tokens: int = 150000) -> str:
    """Truncate text to stay within a token limit.
    
    Args:
        text (str): The text to truncate.
        max_tokens (int): Maximum number of tokens allowed (default: 150000).
        
    Returns:
        str: Truncated text that should be within the token limit.
    """
    if not text:
        return text
        
    estimated_tokens = estimate_tokens(text)
    if estimated_tokens <= max_tokens:
        return text
    
    # Calculate how much to truncate (with some safety margin)
    target_chars = max_tokens * 4 * 0.9  # 90% of estimated limit for safety
    if len(text) > target_chars:
        truncated = text[:int(target_chars)]
        return truncated + "\n\n... [CONTENT TRUNCATED TO PREVENT TOKEN OVERFLOW]"
    
    return text


def get_message_text(msg: AnyMessage) -> str:
    """Get the text content of a message.

    This function extracts the text content from various message formats.

    Args:
        msg (AnyMessage): The message object to extract text from.

    Returns:
        str: The extracted text content of the message.

    Examples:
        >>> from langchain_core.messages import HumanMessage
        >>> get_message_text(HumanMessage(content="Hello"))
        'Hello'
        >>> get_message_text(HumanMessage(content={"text": "World"}))
        'World'
        >>> get_message_text(HumanMessage(content=[{"text": "Hello"}, " ", {"text": "World"}]))
        'Hello World'
    """
    content = msg.content
    if isinstance(content, str):
        return content
    elif isinstance(content, dict):
        return content.get("text", "")
    else:
        txts = [c if isinstance(c, str) else (c.get("text") or "") for c in content]
        return "".join(txts).strip()


def _format_doc(doc: Document, max_content_length: int = 2000) -> str:
    """Format a single document as XML with content truncation.

    Args:
        doc (Document): The document to format.
        max_content_length (int): Maximum length of content to include (default: 2000 chars).

    Returns:
        str: The formatted document as an XML string.
    """
    metadata = doc.metadata or {}
    meta = "".join(f" {k}={v!r}" for k, v in metadata.items())
    if meta:
        meta = f" {meta}"

    # Truncate content if it's too long
    content = doc.page_content
    if len(content) > max_content_length:
        content = content[:max_content_length] + "... [TRUNCATED]"

    return f"<document{meta}>\n{content}\n</document>"


def format_docs_safe(docs: list[Document] | None, max_total_tokens: int = 50000) -> str:
    """Format documents with intelligent token-based truncation.
    
    This function formats documents while staying within token limits by:
    1. Limiting the number of documents
    2. Truncating individual document content
    3. Monitoring total token usage
    
    Args:
        docs (Optional[list[Document]]): Documents to format.
        max_total_tokens (int): Maximum total tokens for all documents (default: 50000).
        
    Returns:
        str: Formatted documents within token limits.
    """
    if not docs:
        return "<documents></documents>"
    
    formatted_docs = []
    total_tokens = 0
    max_doc_tokens = 8000  # Max tokens per document
    
    for i, doc in enumerate(docs):
        # Truncate individual document content to prevent any single doc from being too large
        content = doc.page_content
        doc_tokens = estimate_tokens(content)
        
        if doc_tokens > max_doc_tokens:
            # Truncate this document
            target_chars = max_doc_tokens * 4 * 0.9
            content = content[:int(target_chars)] + "... [DOCUMENT TRUNCATED]"
            doc_tokens = estimate_tokens(content)
        
        # Check if adding this document would exceed our total limit
        if total_tokens + doc_tokens > max_total_tokens:
            if i == 0:
                # If even the first document would exceed limits, truncate it more aggressively
                remaining_tokens = max_total_tokens - 1000  # Leave room for XML markup
                target_chars = remaining_tokens * 4 * 0.9
                content = doc.page_content[:int(target_chars)] + "... [HEAVILY TRUNCATED DUE TO SIZE]"
            else:
                # Stop adding documents, we've reached our limit
                break
        
        # Format this document
        metadata = doc.metadata or {}
        meta = "".join(f" {k}={v!r}" for k, v in metadata.items())
        if meta:
            meta = f" {meta}"
        
        formatted_doc = f"<document{meta}>\n{content}\n</document>"
        formatted_docs.append(formatted_doc)
        total_tokens += estimate_tokens(formatted_doc)
    
    # Create the final result
    formatted = "\n".join(formatted_docs)
    
    # Add truncation note if needed
    truncation_note = ""
    if len(formatted_docs) < len(docs):
        truncation_note = f"\n<!-- Note: Showing {len(formatted_docs)} of {len(docs)} documents (others truncated to prevent token overflow) -->"
    
    result = f"""<documents>
{formatted}{truncation_note}
</documents>"""
    
    # Final safety check
    if estimate_tokens(result) > max_total_tokens:
        # Emergency truncation
        result = truncate_to_token_limit(result, max_total_tokens)
    
    return result
def format_docs(docs: list[Document] | None, max_content_length: int = 2000, max_total_docs: int = 3) -> str:
    """Format a list of documents as XML with content and document limits.

    This function takes a list of Document objects and formats them into a single XML string,
    with content truncation and document count limits to prevent token overflow.

    Args:
        docs (Optional[list[Document]]): A list of Document objects to format, or None.
        max_content_length (int): Maximum length of content per document (default: 2000 chars).
        max_total_docs (int): Maximum number of documents to include (default: 3).

    Returns:
        str: A string containing the formatted documents in XML format.

    Examples:
        >>> docs = [Document(page_content="Hello"), Document(page_content="World")]
        >>> print(format_docs(docs))
        <documents>
        <document>
        Hello
        </document>
        <document>
        World
        </document>
        </documents>

        >>> print(format_docs(None))
        <documents></documents>
    """
    if not docs:
        return "<documents></documents>"
    
    # Limit the number of documents to prevent token overflow
    limited_docs = docs[:max_total_docs]
    
    formatted = "\n".join(_format_doc(doc, max_content_length) for doc in limited_docs)
    
    # Add a note if we had to truncate documents
    truncation_note = ""
    if len(docs) > max_total_docs:
        truncation_note = f"\n<!-- Note: Showing {max_total_docs} of {len(docs)} documents to prevent token overflow -->"
    
    return f"""<documents>
{formatted}{truncation_note}
</documents>"""


def load_chat_model(fully_specified_name: str) -> BaseChatModel:
    """Load a chat model from a fully specified name.

    Args:
        fully_specified_name (str): String in the format 'provider/model'.
    """
    if "/" in fully_specified_name:
        provider, model = fully_specified_name.split("/", maxsplit=1)
    else:
        provider = ""
        model = fully_specified_name
    return init_chat_model(model, model_provider=provider)


async def extract_text_from_pdf_url(pdf_url: str) -> str:
    """Extract text content from a PDF URL.

    Args:
        pdf_url (str): URL pointing to a PDF file.

    Returns:
        str: Extracted text content from the PDF.
    """
    if not DOCUMENT_PROCESSING_AVAILABLE:
        return "Document processing dependencies not available. Please install: pip install aiohttp PyPDF2"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(pdf_url) as response:
                if response.status == 200:
                    pdf_content = await response.read()
                    pdf_file = io.BytesIO(pdf_content)
                    pdf_reader = PyPDF2.PdfReader(pdf_file)

                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"

                    return text.strip()
                else:
                    return f"Failed to download PDF: HTTP {response.status}"
    except Exception as e:
        return f"Error processing PDF: {str(e)}"


async def extract_text_from_web_url(web_url: str) -> str:
    """Extract text content from a web URL.

    Args:
        web_url (str): URL pointing to a web page.

    Returns:
        str: Extracted text content from the web page.
    """
    if not DOCUMENT_PROCESSING_AVAILABLE:
        return "Document processing dependencies not available. Please install: pip install aiohttp beautifulsoup4"

    try:
        from bs4 import BeautifulSoup

        async with aiohttp.ClientSession() as session:
            async with session.get(web_url) as response:
                if response.status == 200:
                    html_content = await response.text()
                    soup = BeautifulSoup(html_content, "html.parser")

                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()

                    # Extract text
                    text = soup.get_text()

                    # Clean up whitespace
                    lines = (line.strip() for line in text.splitlines())
                    chunks = (
                        phrase.strip() for line in lines for phrase in line.split("  ")
                    )
                    text = " ".join(chunk for chunk in chunks if chunk)

                    return text
                else:
                    return f"Failed to access URL: HTTP {response.status}"
    except ImportError:
        return "BeautifulSoup not available. Please install with: pip install beautifulsoup4"
    except Exception as e:
        return f"Error processing web page: {str(e)}"


async def create_documents_from_urls(urls: List[str]) -> List[Document]:
    """Create Document objects from a list of URLs with enhanced error handling and content validation.

    Args:
        urls (List[str]): List of URLs to process.

    Returns:
        List[Document]: List of Document objects with extracted content or error information.
    """
    if not DOCUMENT_PROCESSING_AVAILABLE:
        logging.warning(
            "Document processing dependencies not available. Please install: pip install aiohttp PyPDF2 beautifulsoup4"
        )
        # Return documents with error information instead of empty list
        return [
            Document(
                page_content="Document processing dependencies not available. Please install: pip install aiohttp PyPDF2 beautifulsoup4",
                metadata={"source": url, "type": "error", "title": "Dependency Error", "extraction_success": False}
            ) for url in urls
        ]

    documents = []

    async def process_url(url: str) -> Document:
        """Process a single URL and always return a Document (with error info if needed)."""
        try:
            parsed_url = urlparse(url)
            if parsed_url.path.lower().endswith(".pdf"):
                content = await extract_text_from_pdf_url(url)
                doc_type = "pdf"
            else:
                content = await extract_text_from_web_url(url)
                doc_type = "webpage"

            # Determine if extraction was successful
            extraction_success = not (
                content.startswith(("Failed", "Error", "Document processing dependencies")) or
                content == url or
                len(content.strip()) < 100
            )

            return Document(
                page_content=content,
                metadata={
                    "source": url,
                    "type": doc_type,
                    "title": parsed_url.path.split("/")[-1] or parsed_url.netloc,
                    "extraction_success": extraction_success,
                    "content_length": len(content.strip())
                },
            )
        except Exception as e:
            logging.error("Error processing %s: %s", url, str(e))
            return Document(
                page_content=f"Error processing URL: {str(e)}",
                metadata={
                    "source": url,
                    "type": "error",
                    "title": "Processing Error",
                    "extraction_success": False,
                    "content_length": 0
                },
            )

    # Process all URLs concurrently using gather
    tasks = [process_url(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, Document):
            documents.append(result)
        elif isinstance(result, Exception):
            # Handle exceptions that weren't caught in process_url
            source_url = urls[i] if i < len(urls) else "Unknown"
            documents.append(
                Document(
                    page_content=f"Exception during processing: {str(result)}",
                    metadata={
                        "source": source_url,
                        "type": "error",
                        "title": "Processing Exception",
                        "extraction_success": False,
                        "content_length": 0
                    },
                )
            )

    return documents

def format_docs_with_citations(docs: list | Document) -> str:
    """Format documents with enhanced citation information.

    Args:
        docs (Optional[list[Document]]): Documents to format.

    Returns:
        str: Formatted documents with citation metadata.
    """
    if not docs:
        return "<documents></documents>"

    formatted = []
    for i, doc in enumerate(docs, 1):
        metadata = doc.metadata or {}
        source = metadata.get("source", f"Document_{i}")
        title = metadata.get("title", f"Document {i}")
        doc_type = metadata.get("type", "unknown")

        citation_info = f'title="{title}" source="{source}" type="{doc_type}"'
        formatted.append(f"<document {citation_info}>\n{doc.page_content}\n</document>")

    return f"""<documents>
{chr(10).join(formatted)}
</documents>"""
