"""Main entrypoint for the conversational retrieval graph.

This module defines the core structure and functionality of the conversational
retrieval graph. It includes the main graph definition, state management,
and key functions for processing user inputs, generating queries, retrieving
relevant documents, and formulating responses.
"""

from typing import Literal, cast

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import StateGraph
from pydantic import BaseModel

from retrieval_graph import prompts, retrieval
from retrieval_graph.configuration import Configuration
from retrieval_graph.state import InputState, State
from retrieval_graph.utils import format_docs_safe, get_message_text, load_chat_model

# Define the function that calls the model

class QueryClassification(BaseModel):
    """Classification of user query into subject areas."""
    
    subject: Literal["science", "history", "literature", "general"]


class CritiqueDecision(BaseModel):
    """Decision from critique agent whether to retry or respond."""
    
    decision: Literal["respond", "retry", "improve_query"]
    reasoning: str


async def classify_query(
    state: State, *, config: RunnableConfig
) -> dict[str, str]:
    """Classify the user's query into subject areas."""
    configuration = Configuration.from_runnable_config(config)
    
    user_question = get_original_user_question(state)
    
    prompt = ChatPromptTemplate.from_template(prompts.CLASSIFICATION_SYSTEM_PROMPT)
    model = load_chat_model(configuration.query_model).with_structured_output(QueryClassification)
    
    message_value = await prompt.ainvoke({"question": user_question}, config)
    classification = cast(QueryClassification, await model.ainvoke(message_value, config))
    
    return {"classification": classification.subject}


# Helper function to get original user question
def get_original_user_question(state: State) -> str:
    """Extract the original user question from the message history."""
    # Look for the first human message
    for msg in state.messages:
        if hasattr(msg, 'type') and msg.type == 'human':
            return get_message_text(msg)
    
    # Fallback to first message if no human message found
    if state.messages:
        return get_message_text(state.messages[0])
    
    return ""


# Create simple tools using the @tool decorator
@tool
async def retrieve_documents(query: str) -> str:
    """Retrieve documents from the knowledge base using semantic search.
    
    Args:
        query: The search query to use for retrieval
        
    Returns:
        String representation of retrieved documents
    """
    return f"Searching knowledge base for: {query}"

@tool  
async def web_search(query: str) -> str:
    """Search the web for information when local knowledge is insufficient.
    
    Args:
        query: The search query to use for web search
        
    Returns:
        String representation of web search results
    """
    return f"Searching web for: {query}"

# Define tools list for binding to models
tools = [retrieve_documents, web_search]
# Custom tool execution function
async def handle_tool_calls(state: State, config: RunnableConfig) -> dict:
    """Handle tool calls and execute actual retrieval/search."""
    messages_to_add = []
    retrieved_docs = list(state.retrieved_docs) if state.retrieved_docs else []
    
    # Find the last message with tool calls
    last_message = state.messages[-1] if state.messages else None
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {"messages": messages_to_add, "retrieved_docs": retrieved_docs}
    
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        query = tool_args.get("query", "")
        
        if tool_name == "retrieve_documents":
            try:
                with retrieval.make_retriever(config) as retriever:
                    # Only retrieve a limited number of documents (k=1 by default from configuration)
                    docs = await retriever.ainvoke(query, config)
                    
                    # Add to our retrieved documents list
                    if docs:
                        # Truncate document content before storing to prevent token overflow
                        truncated_docs = []
                        for doc in docs:
                            # Limit individual document content to prevent excessive accumulation
                            content = doc.page_content
                            if len(content) > 3000:  # 3000 chars ~ 750 tokens
                                content = content[:3000] + "... [TRUNCATED FOR TOKEN EFFICIENCY]"
                            
                            truncated_doc = Document(
                                page_content=content,
                                metadata=doc.metadata
                            )
                            truncated_docs.append(truncated_doc)
                        
                        # Only add relevant documents to state
                        retrieved_docs.extend(truncated_docs)
                        
                        # Format a summary of the retrieved documents for the tool response
                        # Keep tool response concise to prevent token overflow
                        docs_content = "\n\n".join([
                            f"Document {i+1}:\nContent: {doc.page_content[:300]}...\nSource: {doc.metadata.get('source', 'Unknown')}"
                            for i, doc in enumerate(docs)
                        ])
                        content = f"Retrieved {len(docs)} relevant document(s):\n\n{docs_content}"
                    else:
                        content = "No documents found in the knowledge base for this query."
                        
                        # If no documents found in local retrieval and we have web search configured,
                        # suggest using web_search tool
                        configuration = Configuration.from_runnable_config(config)
                        if configuration.enable_web_search:
                            content += "\nYou may want to try using web_search for this query."
                        
            except Exception as e:
                content = f"Error during retrieval: {str(e)}"
                
        elif tool_name == "web_search":
            try:
                from langchain_community.tools import TavilySearchResults
                
                # Limit web search results to 3 for more focused and relevant results
                search_tool = TavilySearchResults(max_results=3)
                search_results = search_tool.invoke({"query": query})
                
                web_docs = []
                for result in search_results:
                    if isinstance(result, dict):
                        # Truncate web content to prevent token overflow
                        content = result.get("content", "")
                        if len(content) > 2000:  # Limit web content to 2000 chars
                            content = content[:2000] + "... [WEB CONTENT TRUNCATED]"
                        
                        doc = Document(
                            page_content=content,
                            metadata={
                                "source": result.get("url", ""),
                                "title": result.get("title", ""),
                                "type": "web_search"
                            }
                        )
                        web_docs.append(doc)
                
                # Add to our retrieved documents list
                retrieved_docs.extend(web_docs)
                
                if web_docs:
                    docs_content = "\n\n".join([
                        f"Result {i+1}:\nTitle: {doc.metadata.get('title', 'No title')}\nContent: {doc.page_content[:200]}...\nSource: {doc.metadata.get('source', 'Unknown')}"
                        for i, doc in enumerate(web_docs)
                    ])
                    content = f"Found {len(web_docs)} relevant web result(s):\n\n{docs_content}"
                else:
                    content = "No results found from web search."
                    
            except Exception as e:
                content = f"Error during web search: {str(e)}"
        else:
            content = f"Unknown tool: {tool_name}"
            
        # Add tool message
        tool_message = ToolMessage(
            content=content,
            tool_call_id=tool_call["id"],
            name=tool_name
        )
        messages_to_add.append(tool_message)
    
    # Limit total documents to prevent token overflow in subsequent calls
    if len(retrieved_docs) > 5:
        retrieved_docs = retrieved_docs[-5:]  # Keep only the 5 most recent documents
    
    return {"messages": messages_to_add, "retrieved_docs": retrieved_docs}


# Agent Functions - Simplified specialist agents
async def science_agent(
    state: State, *, config: RunnableConfig
) -> dict:
    """Science subject specialist agent."""
    configuration = Configuration.from_runnable_config(config)
    
    user_question = get_original_user_question(state)
    
    # Check if we have relevant documents
    if not state.retrieved_docs:
        retrieved_docs = f"No documents currently available for the question: '{user_question}'. You MUST use retrieve_documents tool immediately with a search query based on this question."
    else:
        retrieved_docs = format_docs_safe(state.retrieved_docs)
    
    # Create a tool-enabled model
    model = load_chat_model(configuration.response_model).bind_tools(tools)
    
    prompt = ChatPromptTemplate.from_template(prompts.SCIENCE_AGENT_PROMPT)
    
    message_value = await prompt.ainvoke({
        "retrieved_docs": retrieved_docs,
        "question": user_question,
        "critique_feedback": state.critique_feedback or "None"
    }, config)
    
    response = await model.ainvoke(message_value, config)
    
    # Store agent response content for critique
    agent_response_content = response.content if response.content else ""
    
    return {
        "messages": [response],
        "agent_response": agent_response_content
    }


async def history_agent(
    state: State, *, config: RunnableConfig
) -> dict:
    """History subject specialist agent."""
    configuration = Configuration.from_runnable_config(config)
    
    user_question = get_original_user_question(state)
    
    # Check if we have relevant documents
    if not state.retrieved_docs:
        retrieved_docs = f"No documents currently available for the question: '{user_question}'. You MUST use retrieve_documents tool immediately with a search query based on this question."
    else:
        retrieved_docs = format_docs_safe(state.retrieved_docs)
    
    # Create a tool-enabled model
    model = load_chat_model(configuration.response_model).bind_tools(tools)
    
    prompt = ChatPromptTemplate.from_template(prompts.HISTORY_AGENT_PROMPT)
    
    message_value = await prompt.ainvoke({
        "retrieved_docs": retrieved_docs,
        "question": user_question,
        "critique_feedback": state.critique_feedback or "None"
    }, config)
    
    response = await model.ainvoke(message_value, config)
    
    # Store agent response content for critique
    agent_response_content = response.content if response.content else ""
    
    return {
        "messages": [response],
        "agent_response": agent_response_content
    }


async def literature_agent(
    state: State, *, config: RunnableConfig
) -> dict:
    """Literature subject specialist agent."""
    configuration = Configuration.from_runnable_config(config)
    
    user_question = get_original_user_question(state)
    
    # Check if we have relevant documents
    if not state.retrieved_docs:
        retrieved_docs = f"No documents currently available for the question: '{user_question}'. You MUST use retrieve_documents tool immediately with a search query based on this question."
    else:
        retrieved_docs = format_docs_safe(state.retrieved_docs)
    
    # Create a tool-enabled model
    model = load_chat_model(configuration.response_model).bind_tools(tools)
    
    prompt = ChatPromptTemplate.from_template(prompts.LITERATURE_AGENT_PROMPT)
    
    message_value = await prompt.ainvoke({
        "retrieved_docs": retrieved_docs,
        "question": user_question,
        "critique_feedback": state.critique_feedback or "None"
    }, config)
    
    response = await model.ainvoke(message_value, config)
    
    # Store agent response content for critique
    agent_response_content = response.content if response.content else ""
    
    return {
        "messages": [response],
        "agent_response": agent_response_content
    }


async def general_agent(
    state: State, *, config: RunnableConfig
) -> dict:
    """General knowledge specialist agent."""
    configuration = Configuration.from_runnable_config(config)
    
    user_question = get_original_user_question(state)
    
    # Check if we have relevant documents
    if not state.retrieved_docs:
        retrieved_docs = f"No documents currently available for the question: '{user_question}'. You MUST use retrieve_documents tool immediately with a search query based on this question."
    else:
        retrieved_docs = format_docs_safe(state.retrieved_docs)
    
    # Create a tool-enabled model
    model = load_chat_model(configuration.response_model).bind_tools(tools)
    
    prompt = ChatPromptTemplate.from_template(prompts.GENERAL_AGENT_PROMPT)
    
    message_value = await prompt.ainvoke({
        "retrieved_docs": retrieved_docs,
        "question": user_question,
        "critique_feedback": state.critique_feedback or "None"
    }, config)
    
    response = await model.ainvoke(message_value, config)
    
    # Store agent response content for critique
    agent_response_content = response.content if response.content else ""
    
    return {
        "messages": [response],
        "agent_response": agent_response_content
    }


async def critique_agent(
    state: State, *, config: RunnableConfig
) -> dict:
    """Critique and evaluate the specialist agent's response."""
    configuration = Configuration.from_runnable_config(config)
    
    user_question = get_original_user_question(state)
    retrieved_docs = format_docs_safe(state.retrieved_docs) if state.retrieved_docs else "No documents available."
    agent_response = state.agent_response or ""
    
    prompt = ChatPromptTemplate.from_template(prompts.CRITIQUE_SYSTEM_PROMPT)
    model = load_chat_model(configuration.response_model).with_structured_output(CritiqueDecision)
    
    message_value = await prompt.ainvoke({
        "agent_response": agent_response,
        "user_question": user_question,
        "retrieved_docs": retrieved_docs
    }, config)
    
    critique = cast(CritiqueDecision, await model.ainvoke(message_value, config))
    
    return {
        "critique_decision": critique.decision,
        "critique_feedback": critique.reasoning
    }


# Routing functions
def should_continue_to_tools(state: State) -> str:
    """Determine if we should continue to tools or move to critique."""
    last_message = state.messages[-1]
    
    # If the last message has tool calls, go to tools
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    
    # Otherwise, go to critique
    return "critique_agent"


def after_tools_routing(state: State) -> str:
    """Route back to the appropriate specialist agent after tools."""
    classification = state.classification
    if classification == "science":
        return "science_agent"
    elif classification == "history":
        return "history_agent"
    elif classification == "literature":
        return "literature_agent"
    else:
        return "general_agent"


async def respond(
    state: State, *, config: RunnableConfig
) -> dict[str, list[BaseMessage]]:
    """Generate final response based on specialist agent output."""
    from langchain_core.messages import AIMessage
    
    # Use the stored agent response
    agent_response = state.agent_response or "I apologize, but I couldn't generate a proper response."
    
    response = AIMessage(content=agent_response)
    return {"messages": [response]}


# Routing Functions
def route_to_specialist(state: State) -> str:
    """Route to the appropriate specialist agent based on classification."""
    classification = state.classification
    if classification == "science":
        return "science_agent"
    elif classification == "history":
        return "history_agent"
    elif classification == "literature":
        return "literature_agent"
    else:
        return "general_agent"


def critique_router(state: State) -> str:
    """Route based on critique decision."""
    decision = getattr(state, 'critique_decision', 'respond')
    
    if decision == "respond":
        return "respond"
    elif decision == "retry":
        # Go back to the same specialist agent
        return route_to_specialist(state)
    elif decision == "improve_query":
        # Go back to the same specialist agent for better retrieval
        return route_to_specialist(state)
    else:
        return "respond"


# Define the graph with simplified tool calling patterns
builder = StateGraph(State, input=InputState, config_schema=Configuration)

# Add all nodes
builder.add_node("classify_query", classify_query)
builder.add_node("science_agent", science_agent)
builder.add_node("history_agent", history_agent)
builder.add_node("literature_agent", literature_agent)
builder.add_node("general_agent", general_agent)
builder.add_node("tools", handle_tool_calls)  # Tool execution node
builder.add_node("critique_agent", critique_agent)
builder.add_node("respond", respond)

# Define the flow
builder.add_edge("__start__", "classify_query")

# Route to specialist agents after classification
builder.add_conditional_edges(
    "classify_query",
    route_to_specialist,
    {
        "science_agent": "science_agent",
        "history_agent": "history_agent", 
        "literature_agent": "literature_agent",
        "general_agent": "general_agent"
    }
)

# From each specialist agent, check if tools need to be called
builder.add_conditional_edges(
    "science_agent",
    should_continue_to_tools,
    {
        "tools": "tools",
        "critique_agent": "critique_agent"
    }
)

builder.add_conditional_edges(
    "history_agent",
    should_continue_to_tools,
    {
        "tools": "tools",
        "critique_agent": "critique_agent"
    }
)

builder.add_conditional_edges(
    "literature_agent",
    should_continue_to_tools,
    {
        "tools": "tools",
        "critique_agent": "critique_agent"
    }
)

builder.add_conditional_edges(
    "general_agent",
    should_continue_to_tools,
    {
        "tools": "tools",
        "critique_agent": "critique_agent"
    }
)

# After tools, route back to the appropriate specialist agent
builder.add_conditional_edges(
    "tools",
    after_tools_routing,
    {
        "science_agent": "science_agent",
        "history_agent": "history_agent",
        "literature_agent": "literature_agent",
        "general_agent": "general_agent"
    }
)

# Critique routing - can retry or respond
builder.add_conditional_edges(
    "critique_agent",
    critique_router,
    {
        "respond": "respond",
        "science_agent": "science_agent",
        "history_agent": "history_agent", 
        "literature_agent": "literature_agent",
        "general_agent": "general_agent"
    }
)

# Finally, we compile it!
graph = builder.compile(
    interrupt_before=[],
    interrupt_after=[],
)
graph.name = "RetrievalGraph"
