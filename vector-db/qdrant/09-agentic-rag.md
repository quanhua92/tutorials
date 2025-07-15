# Agentic RAG with CrewAI: Beyond Simple Retrieval-Generation

**Source Example:** [agentic_rag_zoom_crewai](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/agentic_rag_zoom_crewai)

## The Core Concept: Why This Example Exists

### The Problem
Traditional RAG systems follow a linear pattern: retrieve relevant documents, then generate a response. But real-world information needs are rarely this simple. When analyzing meeting data, you might need to find specific discussions, calculate statistics across multiple meetings, identify patterns, and synthesize insights from various sources. A linear RAG system struggles with multi-step reasoning, complex analysis, and coordinated information processing.

### The Solution
Agentic RAG transforms information retrieval from a linear process into an intelligent workflow. By combining CrewAI's agent orchestration with Qdrant's vector search capabilities, you create systems where specialized AI agents work together to research, analyze, and synthesize information. Each agent has specific tools and expertise, enabling complex multi-step reasoning that traditional RAG cannot achieve.

Qdrant's philosophy for agentic systems: **Intelligent coordination through specialized tools**. By providing vector search as a tool within an agent framework, you enable AI systems to autonomously decide when and how to retrieve information as part of larger reasoning processes.

---

## Practical Walkthrough: Code Breakdown

### The Meeting Intelligence Dataset

The system processes rich meeting data with comprehensive metadata:

```python
# Example meeting structure from Zoom recordings
{
    'userid': 'unique_user_identifier',
    'firstname': 'John',
    'lastname': 'Smith', 
    'email': 'john.smith@company.com',
    'recordings': [{
        'uuid': 'meeting_unique_id',
        'topic': 'Q4 Marketing Strategy Review',
        'start_time': '2024-01-15T14:00:00Z',
        'duration': 45,  # minutes
        'vtt_content': 'Timestamped transcript...',
        'summary': {
            'summary_title': 'Marketing Strategy Review',
            'summary_overview': 'Discussed Q4 campaigns and budget allocation',
            'summary_details': [
                {'label': 'Campaign Performance', 'summary': 'Social media ROI exceeded targets'},
                {'label': 'Budget Allocation', 'summary': 'Reallocated 20% to digital channels'}
            ],
            'next_steps': [
                'Finalize Q1 campaign themes by February 1st',
                'Schedule follow-up with creative team'
            ]
        }
    }]
}
```

**Rich context advantage:** This structured data enables agents to understand not just what was said, but who said it, when, and what actions resulted from the discussion.

### Singleton-Based Data Management

The system uses a singleton pattern for efficient resource management:

```python
class MeetingData:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def _initialize(self):
        self.data_dir = Path(__file__).parent.parent / 'data'
        self.meetings = self._load_meetings()
        
        self.qdrant_client = QdrantClient(
            url=os.getenv('QDRANT_URL'),
            api_key=os.getenv('QDRANT_API_KEY')
        )
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        
        self._ensure_collection_exists()
        self._populate_collection()
```

**Why singleton matters:** Meeting data processing is expensive—loading files, creating embeddings, establishing connections. The singleton ensures these operations happen once, improving performance for multi-agent workflows.

### Intelligent Text Preparation for Embeddings

The system creates rich text representations for vector search:

```python
def _populate_collection(self):
    points = []
    for i, meeting in enumerate(self.meetings):
        # Create comprehensive text for embedding
        text_to_embed = f"""
        Topic: {meeting.get('topic', '')}
        Content: {meeting.get('vtt_content', '')}
        Summary: {json.dumps(meeting.get('summary', {}))}
        """
        
        # Generate embedding with SentenceTransformer
        vector = self.embedding_model.encode(text_to_embed).tolist()
        
        # Create structured point with rich metadata
        points.append(models.PointStruct(
            id=self._base64_to_uuid(meeting.get('uuid')),
            vector=vector,
            payload={
                'topic': meeting.get('topic'),
                'start_time': meeting.get('start_time'),
                'duration': meeting.get('duration'),
                'summary': meeting.get('summary'),
                'vtt_content': meeting.get('vtt_content'),
                'user': meeting.get('user')
            }
        ))
```

**Embedding strategy:** By combining topic, transcript, and summary into a single embedding, the system captures multiple semantic dimensions—enabling search by topic, content discussion, or outcome.

### Custom Tool Architecture for Agents

CrewAI agents work through specialized tools, each with defined schemas and capabilities:

```python
# Tool input validation schemas
class SearchInput(BaseModel):
    """Input schema for search tool."""
    query: str = Field(..., description="The search query")

class AnalysisInput(BaseModel):
    """Input schema for meeting analysis tool."""
    meeting_data: dict = Field(..., description="Meeting data to analyze")

class CalculatorInput(BaseModel):
    """Input schema for calculator tools."""
    a: int = Field(..., description="First number")
    b: int = Field(..., description="Second number")
```

**Schema-driven design:** By defining clear input/output schemas, agents can reliably chain tools together without type errors or mismatched data formats.

### Vector Search Tool: Semantic Meeting Discovery

The core tool bridges natural language queries with vector search:

```python
class SearchMeetingsTool(BaseTool):
    name: str = "search_meetings"
    description: str = "Search through meeting recordings using vector similarity"
    args_schema: Type[BaseModel] = SearchInput

    def _run(self, query: str) -> List[Dict]:
        # Generate query embedding with OpenAI (matching training data)
        response = openai_client.embeddings.create(
            model="text-embedding-ada-002",
            input=query
        )
        query_vector = response.data[0].embedding
        
        # Perform semantic search with quality threshold
        search_results = qdrant_client.search(
            collection_name='zoom_recordings',
            query_vector=query_vector,
            limit=10,
            score_threshold=0.7  # Only return high-confidence matches
        )
        
        # Return structured results for agent processing
        return [
            {
                "score": hit.score,
                "topic": hit.payload.get('topic', 'N/A'),
                "start_time": hit.payload.get('start_time', 'N/A'),
                "duration": hit.payload.get('duration', 'N/A'),
                "summary": hit.payload.get('summary', {}).get('summary_overview', 'N/A')
            }
            for hit in search_results
        ]
```

**Quality control:** The 0.7 score threshold ensures agents only work with highly relevant results, preventing analysis of tangentially related content.

### Advanced Analysis Tool: Claude Integration

The analysis tool brings sophisticated reasoning to retrieved data:

```python
class MeetingAnalysisTool(BaseTool):
    name: str = "analyze_meeting"
    description: str = "Analyze meeting content using Claude"
    args_schema: Type[BaseModel] = AnalysisInput

    def _run(self, meeting_data: dict) -> Dict:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        # Handle both single meetings and meeting collections
        meetings = meeting_data.get('meetings', [])
        if not isinstance(meetings, list):
            meetings = [meeting_data]
            
        # Format meetings for comprehensive analysis
        meetings_text = "\n\n".join([
            f"""Meeting {i+1}:
            Topic: {m.get('topic')}
            Start Time: {m.get('start_time')}
            Duration: {m.get('duration')} minutes
            Summary: {m.get('summary')}"""
            for i, m in enumerate(meetings)
        ])
        
        # Structured analysis prompt
        prompt = f"""
        Please analyze these meetings:
        
        {meetings_text}
        
        Provide:
        1. Key discussion points across all meetings
        2. Main decisions or action items
        3. Overall patterns and insights
        4. Notable participants and their contributions
        5. Recommendations for follow-up
        """
        
        message = client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=1000,
            temperature=0,  # Deterministic analysis
            messages=[{"role": "user", "content": prompt}]
        )
        
        return {
            "meetings_analyzed": len(meetings),
            "analysis": message.content,
            "timestamp": datetime.now().isoformat()
        }
```

**Analysis depth:** The structured prompt ensures consistent, comprehensive analysis across different meeting types and content complexity.

### Multi-Agent Orchestration: Specialized Roles

The system creates agents with distinct specializations:

```python
def get_crew_response(query: str) -> str:
    # Initialize specialized tools
    calculator = CalculatorTool()
    searcher = SearchMeetingsTool()
    analyzer = MeetingAnalysisTool()
    
    # Research Agent: Information gathering and initial analysis
    researcher = Agent(
        role='Research Assistant',
        goal='Find and analyze relevant information',
        backstory="""You are an expert at finding and analyzing information.
                  You know when to use calculations, when to search meetings,
                  and when to perform detailed analysis.""",
        tools=[calculator, searcher, analyzer],
        verbose=True
    )
    
    # Synthesis Agent: Interpretation and communication
    synthesizer = Agent(
        role='Information Synthesizer',
        goal='Create comprehensive and clear responses',
        backstory="""You excel at taking raw information and analysis
                  and creating clear, actionable insights.""",
        verbose=True
    )
```

**Role specialization:** The researcher focuses on data gathering and tool usage, while the synthesizer focuses on interpretation and communication—mirroring effective human teams.

### Task Definition and Workflow Orchestration

Tasks define the workflow between agents:

```python
    # Research Task: Multi-step information gathering
    research_task = Task(
        description=f"""Process this query: '{query}'
                    1. If it involves calculations, use the calculator tool
                    2. If it needs meeting information, use the search tool
                    3. For detailed analysis, use both search and analysis tools
                    Explain your tool selection and process.""",
        expected_output="""A dictionary containing:
                       - The tools used
                       - The raw results from each tool
                       - Any calculations or analysis performed""",
        agent=researcher
    )
    
    # Synthesis Task: Result interpretation and presentation
    synthesis_task = Task(
        description="""Take the research results and create a clear response.
                    Explain the process used and why it was appropriate.
                    Make sure the response directly addresses the original query.""",
        expected_output="""A clear, structured response that includes:
                       - Direct answer to the query
                       - Supporting evidence from the research
                       - Explanation of the process used""",
        agent=synthesizer
    )
```

**Expected outputs:** Defining clear expected outputs ensures agents produce results in formats that subsequent agents can effectively process.

### Crew Execution: Coordinated Intelligence

The crew orchestrates the complete workflow:

```python
    # Create and execute the crew
    crew = Crew(
        agents=[researcher, synthesizer],
        tasks=[research_task, synthesis_task],
        verbose=True  # Enable process visibility
    )
    
    result = crew.kickoff()
    return result
```

**Workflow automation:** The crew handles task dependencies, agent communication, and result aggregation automatically.

### Intelligent Search Fallback Strategy

The system includes sophisticated fallback mechanisms:

```python
def search_meetings(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    # Statistical queries bypass vector search
    if any(word in query.lower() for word in ['average', 'mean', 'total', 'count', 'statistics']):
        return self.meetings

    try:
        # Primary: Vector-based semantic search
        response = self.openai_client.embeddings.create(
            model="text-embedding-ada-002",
            input=query
        )
        query_vector = response.data[0].embedding
        
        vector_results = self.qdrant_client.search(
            collection_name='zoom_recordings',
            query_vector=query_vector,
            limit=10,
            score_threshold=0.7
        )
        
        if vector_results:
            return [format_vector_result(hit) for hit in vector_results]
            
    except Exception as e:
        print(f"Vector search failed: {e}")

    # Fallback: Content-based keyword matching
    matches = []
    for meeting in self.meetings:
        score = 0
        if query.lower() in meeting['topic'].lower():
            score += 0.5
        if query.lower() in meeting.get('vtt_content', '').lower():
            score += 0.3
        if query.lower() in str(meeting.get('summary', '')).lower():
            score += 0.2
        
        if score > 0:
            matches.append(format_content_result(meeting, score))
    
    return sorted(matches, key=lambda x: x['score'], reverse=True)[:limit]
```

**Robust retrieval:** The multi-tier approach ensures users always get relevant results, even when vector search fails or produces poor matches.

---

## Mental Model: Thinking in Agent Workflows

### The Agent Collaboration Architecture

Traditional RAG vs. Agentic RAG represents a fundamental shift in information processing:

```
Traditional RAG:                    Agentic RAG:
Query → Retrieve → Generate         Query → Research Agent → Analysis Agent → Synthesis Agent
                                           ↓         ↓           ↓
                                    Tools: Search  + Calculate + Analyze + Synthesize
```

**The coordination advantage:** Agents can dynamically choose tools, chain operations, and handle complex multi-step reasoning that linear RAG cannot achieve.

### Understanding Tool-Based Architecture

Each tool represents a specialized capability:

```
Tool Ecosystem:
┌─────────────┬──────────────┬─────────────────┬──────────────────┐
│ Vector      │ Calculation  │ Deep Analysis   │ Result Synthesis │
│ Search      │ Engine       │ (Claude)        │ (Agent Logic)    │
│             │              │                 │                  │
│ - Semantic  │ - Statistics │ - Pattern Recog │ - Clarity        │
│ - Similarity│ - Aggregation│ - Insight Gen   │ - Structure      │
│ - Relevance │ - Comparison │ - Action Items  │ - Completeness   │
└─────────────┴──────────────┴─────────────────┴──────────────────┘
```

**Tool specialization:** Each tool excels in specific domains, enabling agents to choose the right approach for different aspects of complex queries.

### The Research-Synthesis Pattern

The two-agent architecture mirrors effective human workflows:

```
Research Agent Pattern:          Synthesis Agent Pattern:
1. Understand the query          1. Receive research results
2. Select appropriate tools      2. Identify key insights
3. Execute information gathering 3. Structure clear response
4. Perform initial analysis      4. Explain methodology
5. Package results for synthesis 5. Address original query
```

**Why two agents work:** Separation of concerns allows each agent to optimize for different cognitive tasks—research vs. communication.

### Understanding Query Intelligence

The system demonstrates different approaches for different query types:

```
Query Type Analysis:
Statistical Queries → Direct data access (bypass vector search)
Content Queries    → Vector search + semantic matching
Complex Analysis   → Vector search + Claude analysis + synthesis
Hybrid Queries     → Multiple tool chains + intelligent fallback
```

**Intelligent routing:** The system automatically adapts its approach based on query characteristics, maximizing efficiency and accuracy.

### The Embedding Strategy for Meeting Data

Meeting data requires special embedding considerations:

```
Meeting Text Composition:
Topic (High Weight)     → Primary semantic signal
Transcript (Medium)     → Detailed content context  
Summary (Medium)        → Structured outcomes
Metadata (Low)          → Temporal/participant context
```

**Multi-faceted representation:** By combining these elements, embeddings capture both what was discussed and what was decided.

### Real-World Scaling Considerations

**Production deployment patterns:**
- Agent pool management for concurrent requests
- Tool result caching for repeated operations
- Progressive complexity (simple queries → simple tools)
- Error recovery and graceful degradation

**Integration considerations:**
- Calendar system integration for meeting context
- User permission and data access controls
- Real-time meeting processing pipelines
- Multi-tenant data isolation

### Further Exploration

**Try this experiment:** Submit the same query multiple times and observe how agents might choose different tool combinations based on available data or previous context.

**Advanced patterns:** Production agentic systems often include planning agents (that design research strategies), validation agents (that verify results), and coordination agents (that manage resource allocation).

**Tool evolution:** The modular architecture enables adding new tools (web search, document analysis, API integrations) without changing agent logic.

---

This tutorial demonstrates how agentic RAG transforms information retrieval from a linear process into an intelligent workflow. By combining CrewAI's agent orchestration with Qdrant's vector search capabilities, you create systems that can reason, plan, and synthesize information in ways that mirror human analytical processes while operating at machine scale and speed.