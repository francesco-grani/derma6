# Task requirements

## Core requirements

1. **RAG Implementation:**
   - Create a knowledge base relevant to your domain
   - Implement standard document retrieval with embeddings
   - Use chunking strategies and similarity search

2. **Tool Calling:**
   - Implement at least 3 different tool calls
   - Functions should be relevant to your domain
   - Examples: data analysis, calculations, API integrations

3. **Domain Specialisation:**
   - Choose a specific domain or use case
   - Create a focused knowledge base
   - Implement domain-specific prompts and responses
   - Add relevant security measures for your domain

4. **Technical Implementation:**
   - Use LangChain with OpenRouter (OpenAI-compatible SDK) for LLM integration
   - Implement proper error handling
   - Add logging and monitoring
   - Include user input validation
   - Implement rate limiting and API key management

5. **User Interface:**
   - Create an intuitive interface using Streamlit or Next.js
   - Show relevant context and sources
   - Display tool call results
   - Include progress indicators for long operations

---

## Optional tasks

After the main functionality is implemented and your code works correctly, and you feel that you want to upgrade your project, choose one or more improvements from this list. The list is sorted by difficulty level.

**Caution: Some of the tasks in medium or hard categories may involve concepts or libraries that are introduced in later sections or even require outside knowledge/time to research outside of the course.**

### Easy

1. Add conversation history and export functionality
2. Add visualisation of RAG process
3. Include source citations in responses
4. Add an interactive help feature or chatbot guide

### Medium

1. Implement multi-model support (OpenAI, Anthropic, etc.)
2. Add real-time data updates to knowledge base
3. Implement advanced caching strategies
4. Add user authentication and personalisation
5. Calculate and display token usage and costs
6. Add visualisation of tool call results
7. Implement conversation export in various formats (PDF, CSV, JSON)
8. Connect to tools from a publicly available remote MCP server

### Hard

1. Deploy to cloud with proper scaling
2. Implement advanced indexing (e.g., RAPTOR, ColBERT)
3. Implement A/B testing for different RAG strategies
4. Add automated knowledge base updates
5. Fine-tune the model for your specific domain
6. Add multi-language support
7. Implement advanced analytics dashboard
8. Implement your tools (functions) as MCP servers
9. Implement an evaluation of your RAG system, using RAGAs or otherwise

---

## Evaluation criteria

- **Understanding Core Concepts:**
  - The learner understands the basic principles of how RAG works
  - The learner can explain tool calling implementation clearly
  - The learner demonstrates good code organisation practices
  - The learner can identify potential error scenarios and edge cases

- **Technical Implementation:**
  - The learner knows how to use a front-end library using their knowledge and/or external resources
  - The learner's project works as intended; you can chat with a chatbot and get answers
  - The learner has created a relevant knowledge base for their domain
  - The learner has implemented appropriate security considerations

- **Reflection and Improvement:**
  - The learner understands the potential problems with the application
  - The learner can offer suggestions on improving the code and the project

- **Bonus Points:**
  - For maximum points, the learner should implement at least 2 medium and 1 hard optional task.
