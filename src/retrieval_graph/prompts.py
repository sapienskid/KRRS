"""Default prompts."""

RESPONSE_SYSTEM_PROMPT = """You are a helpful AI assistant. Answer the user's questions based on the retrieved documents.

{retrieved_docs}

System time: {system_time}"""
QUERY_SYSTEM_PROMPT = """Generate search queries to retrieve documents that may help answer the user's question. Previously, you made the following queries:
    
<previous_queries/>
{queries}
</previous_queries>

System time: {system_time}"""

CLASSIFICATION_SYSTEM_PROMPT = """You are an educational query classifier. Analyze the user's question and determine which subject area it belongs to.

Subject Areas:
- science: Physics, chemistry, biology, mathematics, computer science, engineering
- history: Historical events, people, civilizations, wars, politics, social movements
- literature: Books, authors, poetry, literary analysis, writing techniques, genres
- general: General knowledge, current events, practical questions, other topics

Respond with ONLY the subject area name: science, history, literature, or general.

Examples:
- "What is photosynthesis?" → science
- "Who was Napoleon?" → history
- "What is the theme of Romeo and Juliet?" → literature
- "How do I change a tire?" → general

User Question: {question}"""