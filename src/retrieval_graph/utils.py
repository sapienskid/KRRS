"""Utility functions for the retrieval graph.

This module contains utility functions for handling messages, documents,
and other common operations in project.

Functions:
    get_message_text: Extract text content from various message formats.
    format_docs: Convert documents to an xml-formatted string.
"""

from typing import Optional, List

from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage

# Optional imports for document processing
try:
    import asyncio
    import aiohttp
    import PyPDF2
    import io
    from urllib.parse import urlparse
    DOCUMENT_PROCESSING_AVAILABLE = True
except ImportError:
    DOCUMENT_PROCESSING_AVAILABLE = False


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


def _format_doc(doc: Document) -> str:
    """Format a single document as XML.

    Args:
        doc (Document): The document to format.

    Returns:
        str: The formatted document as an XML string.
    """
    metadata = doc.metadata or {}
    meta = "".join(f" {k}={v!r}" for k, v in metadata.items())
    if meta:
        meta = f" {meta}"

    return f"<document{meta}>\n{doc.page_content}\n</document>"


def format_docs(docs: Optional[list[Document]]) -> str:
    """Format a list of documents as XML.

    This function takes a list of Document objects and formats them into a single XML string.

    Args:
        docs (Optional[list[Document]]): A list of Document objects to format, or None.

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
    formatted = "\n".join(_format_doc(doc) for doc in docs)
    return f"""<documents>
{formatted}
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
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    text = " ".join(chunk for chunk in chunks if chunk)

                    return text
                else:
                    return f"Failed to access URL: HTTP {response.status}"
    except ImportError:
        return "BeautifulSoup not available. Please install with: pip install beautifulsoup4"
    except Exception as e:
        return f"Error processing web page: {str(e)}"


def create_documents_from_urls(urls: List[str]) -> List[Document]:
    """Create Document objects from a list of URLs (PDFs and web pages).

    Args:
        urls (List[str]): List of URLs to process.

    Returns:
        List[Document]: List of Document objects with extracted content.
    """
    if not DOCUMENT_PROCESSING_AVAILABLE:
        print("Document processing dependencies not available. Please install: pip install aiohttp PyPDF2 beautifulsoup4")
        return []
    
    documents = []

    async def process_url(url: str) -> Optional[Document]:
        try:
            parsed_url = urlparse(url)
            if parsed_url.path.lower().endswith(".pdf"):
                content = await extract_text_from_pdf_url(url)
                doc_type = "pdf"
            else:
                content = await extract_text_from_web_url(url)
                doc_type = "webpage"

            if content and not content.startswith("Failed") and not content.startswith("Error"):
                return Document(
                    page_content=content,
                    metadata={
                        "source": url,
                        "type": doc_type,
                        "title": parsed_url.path.split("/")[-1] or parsed_url.netloc,
                    },
                )
        except Exception as e:
            print(f"Error processing {url}: {str(e)}")

        return None

    async def process_all_urls():
        tasks = [process_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Document):
                documents.append(result)

    # Run the async function
    asyncio.run(process_all_urls())

    return documents


def format_docs_with_citations(docs: Optional[list[Document]]) -> str:
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

        citation_info = f"title=\"{title}\" source=\"{source}\" type=\"{doc_type}\""
        formatted.append(f"<document {citation_info}>\n{doc.page_content}\n</document>")

    return f"""<documents>
{chr(10).join(formatted)}
</documents>"""
