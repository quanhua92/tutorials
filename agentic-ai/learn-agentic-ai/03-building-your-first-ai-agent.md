# Building Your First AI Agent: From Concepts to Code

**Based on:** [01_ai_agents_first](https://github.com/panaversity/learn-agentic-ai/tree/bd868a5030d29df4d816c9d6322899655424b49a/01_ai_agents_first)

## The Core Concept: Why This Example Exists

### The Problem: From API Calls to Autonomous Behavior

Using the OpenAI API directly gives you access to powerful language models, but you're still operating in a request-response paradigm. Each interaction is isolated, and you must manually orchestrate complex workflows. The challenge is creating systems that can:

- **Maintain identity and purpose** across multiple interactions
- **Use tools autonomously** when needed to accomplish goals
- **Hand off tasks** to specialized agents for complex workflows
- **Remember context** and adapt behavior based on ongoing interactions

Building these capabilities manually requires extensive boilerplate code, state management, and orchestration logic—complexity that distracts from your core application logic.

### The Solution: The OpenAI Agents SDK as an Orchestration Layer

The OpenAI Agents SDK transforms the API paradigm from "request-response" to "goal-oriented autonomy." Instead of making isolated API calls, you define agents with:

- **Persistent identity** (instructions and personality)
- **Tool capabilities** (functions they can call autonomously)  
- **Handoff mechanisms** (ability to delegate to specialized agents)
- **Built-in observability** (tracing and debugging capabilities)

The key insight: **Agents are not just AI models with prompts—they're autonomous systems that can reason about when to use tools, when to hand off tasks, and how to maintain context across complex workflows.**

---

## Practical Walkthrough: Code Breakdown

### Understanding the Four Core Primitives

The OpenAI Agents SDK is built around four fundamental concepts that work together to create autonomous behavior.

#### 1. Agents: Identity and Purpose

**File: `examples/01_ai_agents_first/04_hello_agent/readme.md`**

An Agent is more than a configured language model—it's a persistent entity with identity:

```python
from agents import Agent, Runner

# Basic agent with identity and purpose
agent = Agent(
    name="Research Assistant",
    instructions="You are a thorough research assistant specializing in technology trends. Always provide sources and ask clarifying questions when needed.",
    model="gpt-4o-mini"  # Can be configured at agent, run, or global level
)

# Simple interaction
result = await Runner.run(
    agent,
    "What are the latest developments in quantum computing?"
)
print(result.final_output)
```

**Multi-Level Model Configuration:**

The SDK provides flexibility in how you configure which LLM powers your agents:

```python
# Agent Level: Specific model for this agent
agent = Agent(
    name="Haiku Poet",
    instructions="You only respond in haikus.",
    model=OpenAIChatCompletionsModel(
        model="gemini-2.0-flash", 
        openai_client=gemini_client
    )
)

# Run Level: Model configuration for this specific run
config = RunConfig(
    model=OpenAIChatCompletionsModel(model="gpt-4o", openai_client=openai_client),
    tracing_disabled=True
)
result = Runner.run_sync(agent, "Hello", run_config=config)

# Global Level: Default for all agents
set_default_openai_client(external_client)
set_default_openai_api("chat_completions")
```

This flexibility allows you to use different models for different agents or switch providers without changing your agent logic.

#### 2. Tools: Extending Agent Capabilities

**File: `examples/01_ai_agents_first/08_tools/README.md`**

Tools transform agents from text generators into action-oriented systems:

**Function Tools - Converting Python to Agent Capabilities:**
```python
from agents import Agent, function_tool
import requests

@function_tool
def get_weather(location: str) -> str:
    """Get current weather for a location.
    
    Args:
        location: City and country, e.g., "London, UK"
    
    Returns:
        Weather information as a string
    """
    # API call logic here
    response = requests.get(f"https://api.weather.com/v1/current?location={location}")
    return response.json()["description"]

# Agent with tool capability
weather_agent = Agent(
    name="Weather Assistant",
    instructions="Help users get weather information. Use the weather tool when needed.",
    tools=[get_weather]
)

# Agent autonomously decides when to use the tool
result = await Runner.run(
    weather_agent,
    "What's the weather like in Tokyo today?"
)
# Agent will call get_weather("Tokyo, Japan") automatically
```

**Hosted Tools - OpenAI's Pre-built Capabilities:**
```python
from agents import Agent, OpenAIResponsesModel
from agents.tools import WebSearchTool, FileSearchTool

research_agent = Agent(
    name="Research Agent",
    instructions="You are a research assistant that can search the web and files to answer questions thoroughly.",
    model=OpenAIResponsesModel(),  # Required for hosted tools
    tools=[
        WebSearchTool(),      # Real-time web search
        FileSearchTool(),     # Search uploaded documents
    ]
)

result = await Runner.run(
    research_agent,
    "Find the latest research on AI safety measures and summarize the key findings."
)
# Agent will automatically search the web and any uploaded files
```

#### 3. Handoffs: Delegation and Specialization

**File: `examples/01_ai_agents_first/11_handoffs/readme.md`**

Handoffs enable sophisticated multi-agent workflows where agents delegate tasks to specialists:

```python
from agents import Agent, handoff

# Specialized agents for different domains
billing_agent = Agent(
    name="Billing Specialist",
    instructions="You handle all billing inquiries with accuracy and empathy. You have access to billing systems and can process refunds."
)

technical_agent = Agent(
    name="Technical Support",
    instructions="You resolve technical issues step-by-step. You can access system logs and run diagnostics."
)

# Triage agent that routes to specialists
triage_agent = Agent(
    name="Customer Service Triage",
    instructions="""You are the first point of contact for customer service. 
    Analyze the customer's request and hand off to the appropriate specialist:
    - Billing issues → Billing Specialist
    - Technical problems → Technical Support
    - General questions → Handle yourself""",
    handoffs=[billing_agent, technical_agent]
)

# The triage agent will automatically determine which specialist to use
result = await Runner.run(
    triage_agent,
    "My credit card was charged twice for the same order last month"
)
# Automatically hands off to billing_agent
```

**Custom Handoff Behavior:**
```python
# Advanced handoff with custom parameters
custom_handoff = handoff(
    agent=billing_agent,
    tool_name_override="escalate_to_billing",
    tool_description_override="Escalate complex billing issues that require account access"
)

senior_agent = Agent(
    name="Senior Support Agent",
    instructions="Handle escalated issues requiring specialized knowledge.",
    handoffs=[custom_handoff]
)
```

#### 4. Tracing & Observability: Understanding Agent Behavior

The SDK includes built-in observability for debugging and optimization:

```python
from agents import set_tracing_disabled

# Enable detailed tracing (default)
set_tracing_disabled(False)

result = await Runner.run(agent, "Research quantum computing applications")

# Access detailed execution trace
print("Steps taken:", len(result.steps))
for step in result.steps:
    print(f"Step: {step.type}")
    if step.tool_calls:
        print(f"Tools used: {[call.function.name for call in step.tool_calls]}")
```

### Advanced Agent Patterns

#### Agents as Tools: Hierarchical Intelligence
```python
# Sub-agent that can be used as a tool by other agents
data_analyst = Agent(
    name="Data Analyst",
    instructions="Analyze datasets and provide statistical insights.",
    tools=[data_processing_tool]
)

# Main agent that uses the data analyst as a tool
report_generator = Agent(
    name="Report Generator", 
    instructions="Create comprehensive reports using data analysis.",
    tools=[data_analyst]  # Use another agent as a tool
)

# The report generator can delegate data analysis to the specialist
result = await Runner.run(
    report_generator,
    "Create a quarterly sales report from the uploaded CSV file"
)
# Will automatically use data_analyst for analysis, then generate report
```

#### Context and Memory Management
```python
from agents import Context

# Custom context for maintaining state
class CustomerContext(Context):
    customer_id: str
    purchase_history: list
    preferences: dict

agent = Agent(
    name="Personal Shopper",
    instructions="Provide personalized shopping recommendations based on customer history.",
    context_schema=CustomerContext
)

# Context is maintained across interactions
context = CustomerContext(
    customer_id="12345",
    purchase_history=["laptop", "mouse", "keyboard"],
    preferences={"budget": "under_500", "brand": "tech_brands"}
)

result = await Runner.run(
    agent,
    "Recommend accessories for my setup",
    context=context
)
```

---

## Mental Model: Thinking in Autonomous Agents

### Build the Mental Model: Agents as Digital Employees

Think of AI agents like hiring specialized employees for your digital workforce:

**Traditional API Approach = Consulting with Experts**
- You call an expert (API), ask a specific question, get an answer
- No memory of previous conversations
- You must coordinate all the work yourself
- Each interaction is isolated

**Agent Approach = Hiring Dedicated Staff**
- Agents have persistent roles and responsibilities (instructions)
- They remember context and build on previous interactions
- They can use tools autonomously to complete tasks
- They can delegate to other specialists when needed
- They provide detailed logs of their work (tracing)

### Why It's Designed This Way: The Four Pillars of Autonomy

The SDK's architecture reflects four key insights about autonomous AI systems:

1. **Identity First**: Agents need persistent identity (instructions) to maintain consistent behavior across interactions
2. **Capability Extension**: Raw language models need tools to interact with the world beyond text
3. **Specialization Benefits**: Different agents can excel at different tasks, just like human specialists
4. **Observability Requirements**: Autonomous systems need detailed logging to debug and optimize behavior

### Further Exploration: Building Production Agents

**Immediate Practice:**
1. Create a simple agent with one tool and test its autonomous behavior
2. Build a two-agent handoff system (e.g., research → summarize)
3. Experiment with different model providers (OpenAI, Gemini, etc.)

**Real-World Application Design:**

Design a customer support system with:
- **Intake Agent**: Gathers initial information and classifies issues
- **Technical Agent**: Handles technical problems with diagnostic tools
- **Billing Agent**: Processes billing inquiries with payment system access
- **Escalation Agent**: Handles complex cases requiring human intervention

**Architecture Questions:**
- How would you design handoff criteria between agents?
- What tools would each agent need for their specialized tasks?
- How would you maintain customer context across agent handoffs?
- What tracing information would you need for quality assurance?

**Advanced Challenges:**
- Build an agent that can learn from user feedback to improve its tool usage
- Design a multi-agent research system where agents verify each other's findings
- Create agents that can dynamically create and use new tools based on task requirements

---

*You now understand the fundamental building blocks of autonomous AI agents. The progression from API calls to agent orchestration represents a shift from manual coordination to intelligent automation. Next, we'll explore the theoretical foundations that make these agentic systems possible and examine the broader patterns for designing multi-agent architectures.*