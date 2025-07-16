# Advanced Agentic UI Patterns: Building Human-Agent Collaboration Interfaces

**Based on:** [10_advanced_agentic_ui](https://github.com/panaversity/learn-agentic-ai/tree/bd868a5030d29df4d816c9d6322899655424b49a/10_advanced_agentic_ui)

## The Core Concept: Why This Example Exists

### The Problem: Traditional UIs Don't Support Agent Autonomy

Traditional user interfaces were designed for **direct human control**—every action requires explicit user input. This paradigm breaks down when dealing with autonomous AI agents that:

- **Operate asynchronously**: Agents work on tasks over minutes or hours
- **Make independent decisions**: Agents choose tools and approaches autonomously  
- **Collaborate with other agents**: Complex handoffs and coordination occur
- **Process continuously**: Agents handle multiple simultaneous conversations
- **Require oversight**: Humans need visibility into agent reasoning and actions
- **Handle complex workflows**: Multi-step processes with branching logic

Traditional UI patterns fail to provide the **transparency, control, and real-time feedback** needed for effective human-agent collaboration.

### The Solution: Agent-Native User Interface Patterns

**Advanced agentic UI patterns** bridge the gap between autonomous agent capabilities and human oversight needs by providing:

- **Real-time transparency**: Live visibility into agent reasoning and actions
- **Asynchronous interaction**: UIs that handle long-running agent processes
- **Multi-agent coordination**: Visualizing complex agent workflows and handoffs
- **Adaptive control**: Allowing humans to intervene or guide agent behavior
- **Contextual oversight**: Showing relevant information at the right time
- **Trust building**: Making agent decision-making processes understandable

The key insight: **Agent UIs must transform from command interfaces to collaboration interfaces—supporting both agent autonomy and human oversight in a seamless, intuitive experience.**

---

## Practical Walkthrough: Code Breakdown

### Foundation Layer: Conversational-First UI with Chainlit

Chainlit provides the most specialized framework for building conversational agent interfaces with built-in support for streaming, tool visualization, and agent handoffs.

#### Real-Time Agent Conversation Interface

**Streaming Agent Responses with Tool Visualization:**
```python
import chainlit as cl
from agents import Agent, Runner
from typing import AsyncGenerator
import asyncio

@cl.on_chat_start
async def start_conversation():
    """Initialize agent conversation"""
    
    # Create specialized agent
    research_agent = Agent(
        name="Research Assistant",
        instructions="""
        You are an advanced research assistant that can:
        - Search for information using web tools
        - Analyze documents and data
        - Generate comprehensive reports
        - Coordinate with other specialist agents when needed
        
        Always show your reasoning process and explain the tools you're using.
        """
    )
    
    # Store agent in session
    cl.user_session.set("agent", research_agent)
    cl.user_session.set("conversation_history", [])
    
    # Welcome message with starter prompts
    await cl.Message(
        content="🤖 **Research Assistant Ready**\n\nI can help you with research, analysis, and information gathering. I'll show you my reasoning process and tool usage in real-time.",
        author="System"
    ).send()
    
    # Set starter prompts to guide user interactions
    await cl.set_starters([
        cl.Starter(
            label="Research a technology trend",
            message="Research the latest developments in quantum computing and provide a comprehensive analysis.",
            icon="🔬"
        ),
        cl.Starter(
            label="Analyze market data",
            message="Analyze the current AI market trends and predict future developments.",
            icon="📊"
        ),
        cl.Starter(
            label="Compare solutions",
            message="Compare different approaches to sustainable energy storage.",
            icon="⚖️"
        ),
        cl.Starter(
            label="Generate report",
            message="Create a comprehensive report on the impact of AI on healthcare.",
            icon="📄"
        )
    ])

@cl.on_message
async def handle_message(message: cl.Message):
    """Handle incoming user messages with real-time agent processing"""
    
    agent = cl.user_session.get("agent")
    conversation_history = cl.user_session.get("conversation_history", [])
    
    # Create response message that will be streamed
    response_msg = cl.Message(
        content="",
        author="Research Assistant"
    )
    
    # Start the response
    await response_msg.send()
    
    try:
        # Process message through agent with real-time updates
        async for event in process_agent_request(agent, message.content, response_msg):
            # Update conversation history
            if event.get("type") == "final_response":
                conversation_history.append({
                    "user": message.content,
                    "assistant": event.get("content"),
                    "tools_used": event.get("tools_used", []),
                    "timestamp": event.get("timestamp")
                })
                cl.user_session.set("conversation_history", conversation_history)
                
                # Add usage metrics
                await display_usage_metrics(event.get("metrics", {}))
                
    except Exception as e:
        await cl.Message(
            content=f"❌ **Error**: {str(e)}\n\nPlease try again or rephrase your request.",
            author="System"
        ).send()

async def process_agent_request(
    agent: Agent, 
    user_input: str, 
    response_msg: cl.Message
) -> AsyncGenerator[dict, None]:
    """Process agent request with real-time UI updates"""
    
    tools_used = []
    reasoning_steps = []
    
    # Show initial thinking state
    await response_msg.stream_token("🤔 **Analyzing your request...**\n\n")
    await asyncio.sleep(0.5)
    
    # Step 1: Planning Phase
    with cl.Step(name="Planning", type="planning") as planning_step:
        planning_step.output = "Breaking down the request and identifying required tools..."
        
        # Simulate planning process
        await asyncio.sleep(1)
        plan = await create_research_plan(user_input)
        
        planning_step.output = f"**Research Plan:**\n{plan}"
        
        await response_msg.stream_token(f"📋 **Planning Phase Complete**\n\n")
        reasoning_steps.append({"phase": "planning", "output": plan})
    
    # Step 2: Information Gathering
    with cl.Step(name="Information Gathering", type="tool") as gather_step:
        gather_step.output = "Searching for relevant information..."
        
        # Simulate tool usage
        web_search_results = await simulate_web_search(user_input)
        tools_used.append("web_search")
        
        gather_step.output = f"**Web Search Results:**\n{web_search_results['summary']}"
        
        await response_msg.stream_token(f"🔍 **Information Gathered**\n\n")
        reasoning_steps.append({"phase": "gathering", "output": web_search_results})
    
    # Step 3: Analysis Phase  
    with cl.Step(name="Analysis", type="analysis") as analysis_step:
        analysis_step.output = "Analyzing gathered information..."
        
        # Stream the analysis process
        analysis_parts = [
            "Identifying key trends and patterns...",
            "Cross-referencing multiple sources...", 
            "Evaluating credibility and relevance...",
            "Synthesizing insights..."
        ]
        
        for part in analysis_parts:
            analysis_step.output = part
            await response_msg.stream_token(f"⚡ {part}\n")
            await asyncio.sleep(0.8)
        
        analysis_result = await perform_analysis(web_search_results)
        analysis_step.output = f"**Analysis Complete:**\n{analysis_result}"
        reasoning_steps.append({"phase": "analysis", "output": analysis_result})
    
    # Step 4: Generate Final Response
    await response_msg.stream_token(f"\n📝 **Generating Response...**\n\n")
    
    # Run the actual agent to generate the final response
    final_result = await Runner.run(
        agent,
        f"""Based on the following research and analysis, provide a comprehensive response to: {user_input}

Research Plan: {plan}
Web Search Results: {web_search_results['summary']}
Analysis: {analysis_result}

Provide a well-structured, informative response that addresses the user's request."""
    )
    
    # Stream the final response token by token
    final_response = final_result.final_output
    for token in final_response.split():
        await response_msg.stream_token(f"{token} ")
        await asyncio.sleep(0.05)  # Realistic streaming speed
    
    # Yield final event
    yield {
        "type": "final_response",
        "content": final_response,
        "tools_used": tools_used,
        "reasoning_steps": reasoning_steps,
        "timestamp": "2024-01-01T00:00:00Z",
        "metrics": {
            "tools_called": len(tools_used),
            "reasoning_steps": len(reasoning_steps),
            "response_length": len(final_response),
            "processing_time": "8.2s"
        }
    }

async def create_research_plan(query: str) -> str:
    """Create a structured research plan"""
    return f"""
1. **Primary Research**: Web search for current information on: {query}
2. **Source Analysis**: Evaluate credibility and relevance of sources
3. **Data Synthesis**: Combine information from multiple sources
4. **Insight Generation**: Identify patterns, trends, and implications
5. **Response Formulation**: Structure findings into comprehensive answer
"""

async def simulate_web_search(query: str) -> dict:
    """Simulate web search tool"""
    await asyncio.sleep(2)  # Simulate API call
    return {
        "summary": f"Found 25 relevant sources about '{query}'. Key themes include recent developments, expert opinions, and market analysis.",
        "sources": 25,
        "relevance_score": 0.87
    }

async def perform_analysis(search_results: dict) -> str:
    """Perform analysis of search results"""
    await asyncio.sleep(1.5)
    return f"Analysis reveals 3 major trends, 5 key insights, and 2 areas requiring further investigation. Confidence level: {search_results['relevance_score']:.0%}"

async def display_usage_metrics(metrics: dict):
    """Display usage and performance metrics"""
    metrics_content = f"""
**📊 Session Metrics**
- Tools Used: {metrics.get('tools_called', 0)}
- Reasoning Steps: {metrics.get('reasoning_steps', 0)}
- Response Length: {metrics.get('response_length', 0)} characters
- Processing Time: {metrics.get('processing_time', 'N/A')}
"""
    
    await cl.Message(
        content=metrics_content,
        author="System",
        type="system_info"
    ).send()

# Agent handoff visualization
@cl.step(type="handoff")
async def visualize_agent_handoff(source_agent: str, target_agent: str, task: str):
    """Visualize agent-to-agent handoffs"""
    
    handoff_message = f"""
🔄 **Agent Handoff**

**From:** {source_agent}
**To:** {target_agent}
**Task:** {task}

The specialized agent is now taking over this part of the workflow.
"""
    
    return handoff_message
```

### Data-Driven Interface Layer: Streamlit for Agent Analytics

Streamlit excels at creating data-rich interfaces for monitoring and analyzing agent performance.

#### Agent Performance Dashboard

**Multi-Agent System Monitoring:**
```python
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import asyncio

st.set_page_config(
    page_title="Agent Control Center",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

def main():
    st.title("🤖 Agent Control Center")
    st.markdown("Real-time monitoring and control for multi-agent systems")
    
    # Sidebar for agent selection and controls
    with st.sidebar:
        st.header("🎛️ Agent Controls")
        
        # Agent selection
        available_agents = get_available_agents()
        selected_agents = st.multiselect(
            "Select Agents to Monitor",
            available_agents,
            default=available_agents[:3]
        )
        
        # Time range selector
        time_range = st.selectbox(
            "Time Range",
            ["Last Hour", "Last 6 Hours", "Last 24 Hours", "Last 7 Days"]
        )
        
        # Refresh controls
        auto_refresh = st.checkbox("Auto Refresh", value=True)
        if st.button("🔄 Refresh Now"):
            st.rerun()
    
    # Main dashboard layout
    if selected_agents:
        # Agent status overview
        display_agent_status_overview(selected_agents)
        
        # Performance metrics
        display_performance_metrics(selected_agents, time_range)
        
        # Active conversations
        display_active_conversations(selected_agents)
        
        # Agent interactions and handoffs
        display_agent_interactions(selected_agents, time_range)
        
    else:
        st.info("👆 Select agents from the sidebar to begin monitoring")
    
    # Auto-refresh functionality
    if auto_refresh:
        import time
        time.sleep(30)
        st.rerun()

def display_agent_status_overview(selected_agents):
    """Display real-time agent status"""
    st.header("📊 Agent Status Overview")
    
    # Create columns for each agent
    cols = st.columns(len(selected_agents))
    
    for i, agent_id in enumerate(selected_agents):
        with cols[i]:
            agent_status = get_agent_status(agent_id)
            
            # Status card
            status_color = {
                "active": "🟢",
                "busy": "🟡", 
                "error": "🔴",
                "offline": "⚫"
            }
            
            st.metric(
                label=f"{status_color.get(agent_status['status'], '❓')} {agent_status['name']}",
                value=f"{agent_status['active_tasks']} tasks",
                delta=f"{agent_status['completed_today']} completed today"
            )
            
            # Quick stats
            st.write(f"**Uptime:** {agent_status['uptime']}")
            st.write(f"**Load:** {agent_status['cpu_percent']:.1f}% CPU")
            st.write(f"**Memory:** {agent_status['memory_mb']:.0f} MB")
            
            # Quick actions
            col1, col2 = st.columns(2)
            with col1:
                if st.button("⏸️ Pause", key=f"pause_{agent_id}"):
                    pause_agent(agent_id)
                    st.success("Agent paused")
            with col2:
                if st.button("🔄 Restart", key=f"restart_{agent_id}"):
                    restart_agent(agent_id)
                    st.success("Agent restarted")

def display_performance_metrics(selected_agents, time_range):
    """Display detailed performance metrics"""
    st.header("📈 Performance Metrics")
    
    # Get performance data
    perf_data = get_performance_data(selected_agents, time_range)
    
    # Response time trends
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Response Time Trends")
        fig_response = px.line(
            perf_data, 
            x='timestamp', 
            y='response_time_ms',
            color='agent_id',
            title="Average Response Time Over Time"
        )
        st.plotly_chart(fig_response, use_container_width=True)
    
    with col2:
        st.subheader("Task Completion Rate")
        fig_completion = px.bar(
            perf_data.groupby('agent_id').agg({
                'tasks_completed': 'sum',
                'tasks_failed': 'sum'
            }).reset_index(),
            x='agent_id',
            y=['tasks_completed', 'tasks_failed'],
            title="Tasks Completed vs Failed"
        )
        st.plotly_chart(fig_completion, use_container_width=True)
    
    # Token usage analysis
    st.subheader("💰 Token Usage and Costs")
    
    token_data = get_token_usage_data(selected_agents, time_range)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_tokens = token_data['total_tokens'].sum()
        st.metric("Total Tokens", f"{total_tokens:,}")
    
    with col2:
        total_cost = token_data['estimated_cost'].sum()
        st.metric("Estimated Cost", f"${total_cost:.2f}")
    
    with col3:
        avg_tokens_per_request = token_data['tokens_per_request'].mean()
        st.metric("Avg Tokens/Request", f"{avg_tokens_per_request:.0f}")
    
    # Cost breakdown chart
    fig_cost = px.pie(
        token_data,
        values='estimated_cost',
        names='agent_id',
        title="Cost Distribution by Agent"
    )
    st.plotly_chart(fig_cost, use_container_width=True)

def display_active_conversations(selected_agents):
    """Display and manage active conversations"""
    st.header("💬 Active Conversations")
    
    active_convos = get_active_conversations(selected_agents)
    
    if not active_convos.empty:
        # Conversation list with management controls
        for idx, convo in active_convos.iterrows():
            with st.expander(
                f"🗣️ {convo['user_id']} → {convo['agent_id']} ({convo['duration']})",
                expanded=False
            ):
                col1, col2, col3 = st.columns([3, 1, 1])
                
                with col1:
                    st.write(f"**Last Message:** {convo['last_message'][:100]}...")
                    st.write(f"**Status:** {convo['status']}")
                    st.write(f"**Messages:** {convo['message_count']}")
                
                with col2:
                    if st.button("👁️ View", key=f"view_{convo['conversation_id']}"):
                        display_conversation_details(convo['conversation_id'])
                
                with col3:
                    if st.button("⏹️ End", key=f"end_{convo['conversation_id']}"):
                        end_conversation(convo['conversation_id'])
                        st.success("Conversation ended")
                        st.rerun()
    else:
        st.info("No active conversations")

def display_agent_interactions(selected_agents, time_range):
    """Display agent-to-agent interactions and handoffs"""
    st.header("🔄 Agent Interactions")
    
    interaction_data = get_agent_interactions(selected_agents, time_range)
    
    if not interaction_data.empty:
        # Network graph of agent interactions
        st.subheader("Agent Collaboration Network")
        
        # Create network graph using plotly
        fig_network = create_agent_network_graph(interaction_data)
        st.plotly_chart(fig_network, use_container_width=True)
        
        # Interaction timeline
        st.subheader("Handoff Timeline")
        
        fig_timeline = px.timeline(
            interaction_data,
            x_start='start_time',
            x_end='end_time',
            y='source_agent',
            color='target_agent',
            title="Agent Handoff Timeline"
        )
        st.plotly_chart(fig_timeline, use_container_width=True)
        
        # Detailed interaction log
        st.subheader("Interaction Log")
        
        # Filterable and searchable interaction log
        search_term = st.text_input("🔍 Search interactions...")
        
        if search_term:
            filtered_interactions = interaction_data[
                interaction_data['description'].str.contains(search_term, case=False)
            ]
        else:
            filtered_interactions = interaction_data
        
        st.dataframe(
            filtered_interactions[['timestamp', 'source_agent', 'target_agent', 'task_type', 'status']],
            use_container_width=True
        )
    else:
        st.info("No agent interactions in selected time range")

# Real-time chat interface for agent testing
def display_agent_chat_interface():
    """Real-time chat interface for testing agents"""
    st.header("💬 Agent Chat Interface")
    
    # Agent selection for chat
    available_agents = get_available_agents()
    selected_agent = st.selectbox("Select Agent to Chat With", available_agents)
    
    if selected_agent:
        # Initialize conversation history
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []
        
        # Display conversation history
        for i, message in enumerate(st.session_state.chat_history):
            with st.chat_message(message["role"]):
                st.write(message["content"])
                
                # Show metadata for agent messages
                if message["role"] == "assistant" and "metadata" in message:
                    with st.expander("📊 Message Details"):
                        st.json(message["metadata"])
        
        # Chat input
        if prompt := st.chat_input("Type your message..."):
            # Add user message to history
            st.session_state.chat_history.append({
                "role": "user",
                "content": prompt
            })
            
            # Display user message
            with st.chat_message("user"):
                st.write(prompt)
            
            # Process with agent and stream response
            with st.chat_message("assistant"):
                response_placeholder = st.empty()
                
                # Simulate streaming response
                full_response = ""
                agent_response = process_agent_message(selected_agent, prompt)
                
                for chunk in agent_response:
                    full_response += chunk
                    response_placeholder.write(full_response + "▋")
                
                response_placeholder.write(full_response)
                
                # Add agent response to history with metadata
                st.session_state.chat_history.append({
                    "role": "assistant",
                    "content": full_response,
                    "metadata": {
                        "agent_id": selected_agent,
                        "response_time": "1.2s",
                        "tokens_used": len(full_response.split()),
                        "tools_called": ["web_search", "analysis"]
                    }
                })

# Helper functions (these would connect to actual agent systems)
def get_available_agents():
    """Get list of available agents"""
    return ["research-agent-1", "analysis-agent-2", "synthesis-agent-3", "review-agent-4"]

def get_agent_status(agent_id):
    """Get current status of an agent"""
    import random
    return {
        "name": agent_id.replace("-", " ").title(),
        "status": random.choice(["active", "busy", "offline"]),
        "active_tasks": random.randint(0, 5),
        "completed_today": random.randint(10, 50),
        "uptime": "2d 14h 32m",
        "cpu_percent": random.uniform(10, 80),
        "memory_mb": random.uniform(512, 2048)
    }

def get_performance_data(selected_agents, time_range):
    """Get performance data for selected agents"""
    # Generate sample data
    dates = pd.date_range(end=datetime.now(), periods=24, freq='H')
    data = []
    
    for agent in selected_agents:
        for date in dates:
            data.append({
                "timestamp": date,
                "agent_id": agent,
                "response_time_ms": random.uniform(500, 3000),
                "tasks_completed": random.randint(5, 20),
                "tasks_failed": random.randint(0, 3)
            })
    
    return pd.DataFrame(data)

if __name__ == "__main__":
    main()
```

### Production Interface Layer: Custom React Components with FastAPI

For production applications, custom React interfaces provide maximum flexibility and performance.

#### Custom Agent UI Components

**React Components for Agent Interfaces:**
```typescript
// AgentChatInterface.tsx
import React, { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Loader2, MessageSquare, Bot, User, Zap, Clock } from 'lucide-react';

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  metadata?: {
    agent_id?: string;
    tools_used?: string[];
    processing_time?: number;
    tokens_used?: number;
  };
}

interface AgentStatus {
  id: string;
  name: string;
  status: 'idle' | 'thinking' | 'using_tool' | 'responding' | 'error';
  current_task?: string;
  progress?: number;
}

export default function AgentChatInterface({ agentId }: { agentId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // WebSocket connection for real-time updates
  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/agents/${agentId}/stream`);
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'agent_status') {
        setAgentStatus(data.status);
      } else if (data.type === 'message_chunk') {
        updateStreamingMessage(data.chunk);
      } else if (data.type === 'message_complete') {
        finalizeMessage(data.message);
      }
    };
    
    return () => ws.close();
  }, [agentId]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await fetch(`/api/agents/${agentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: input })
      });

      if (!response.ok) throw new Error('Failed to send message');
      
    } catch (error) {
      console.error('Error sending message:', error);
      // Add error message
      const errorMessage: Message = {
        id: Date.now().toString(),
        role: 'system',
        content: 'Sorry, there was an error processing your message.',
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const updateStreamingMessage = (chunk: string) => {
    setMessages(prev => {
      const lastMessage = prev[prev.length - 1];
      if (lastMessage?.role === 'assistant') {
        return [
          ...prev.slice(0, -1),
          { ...lastMessage, content: lastMessage.content + chunk }
        ];
      } else {
        // Start new assistant message
        const newMessage: Message = {
          id: Date.now().toString(),
          role: 'assistant',
          content: chunk,
          timestamp: new Date()
        };
        return [...prev, newMessage];
      }
    });
  };

  const finalizeMessage = (messageData: any) => {
    setMessages(prev => {
      const lastMessage = prev[prev.length - 1];
      if (lastMessage?.role === 'assistant') {
        return [
          ...prev.slice(0, -1),
          {
            ...lastMessage,
            content: messageData.content,
            metadata: messageData.metadata
          }
        ];
      }
      return prev;
    });
    setAgentStatus(prev => prev ? { ...prev, status: 'idle' } : null);
  };

  return (
    <div className="flex flex-col h-screen max-w-4xl mx-auto p-4">
      {/* Agent Status Header */}
      <Card className="mb-4">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              {agentStatus?.name || 'AI Agent'}
            </CardTitle>
            <AgentStatusBadge status={agentStatus?.status || 'idle'} />
          </div>
          {agentStatus?.current_task && (
            <div className="text-sm text-muted-foreground mt-2">
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4" />
                {agentStatus.current_task}
              </div>
              {agentStatus.progress !== undefined && (
                <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
                  <div 
                    className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${agentStatus.progress}%` }}
                  />
                </div>
              )}
            </div>
          )}
        </CardHeader>
      </Card>

      {/* Messages Area */}
      <Card className="flex-1 flex flex-col">
        <CardContent className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {isLoading && <LoadingIndicator />}
          <div ref={messagesEndRef} />
        </CardContent>

        {/* Input Area */}
        <div className="p-4 border-t">
          <div className="flex gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type your message..."
              onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
              disabled={isLoading}
            />
            <Button 
              onClick={sendMessage} 
              disabled={isLoading || !input.trim()}
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Send'}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function AgentStatusBadge({ status }: { status: string }) {
  const statusConfig = {
    idle: { color: 'bg-gray-500', icon: Clock, text: 'Idle' },
    thinking: { color: 'bg-blue-500 animate-pulse', icon: Loader2, text: 'Thinking' },
    using_tool: { color: 'bg-yellow-500', icon: Zap, text: 'Using Tool' },
    responding: { color: 'bg-green-500', icon: MessageSquare, text: 'Responding' },
    error: { color: 'bg-red-500', icon: null, text: 'Error' }
  };

  const config = statusConfig[status as keyof typeof statusConfig] || statusConfig.idle;
  const Icon = config.icon;

  return (
    <Badge className={`${config.color} text-white`}>
      {Icon && <Icon className="h-3 w-3 mr-1" />}
      {config.text}
    </Badge>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`
        max-w-[80%] p-3 rounded-lg
        ${isUser ? 'bg-blue-600 text-white' : 
          isSystem ? 'bg-gray-100 text-gray-800' : 'bg-gray-50 text-gray-900'}
      `}>
        <div className="flex items-center gap-2 mb-1">
          {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
          <span className="text-sm font-medium">
            {isUser ? 'You' : isSystem ? 'System' : 'Agent'}
          </span>
          <span className="text-xs opacity-70">
            {message.timestamp.toLocaleTimeString()}
          </span>
        </div>
        
        <div className="whitespace-pre-wrap">{message.content}</div>
        
        {/* Message metadata */}
        {message.metadata && (
          <MessageMetadata metadata={message.metadata} />
        )}
      </div>
    </div>
  );
}

function MessageMetadata({ metadata }: { metadata: any }) {
  return (
    <div className="mt-2 pt-2 border-t border-opacity-20 text-xs">
      <div className="flex gap-4 text-gray-500">
        {metadata.processing_time && (
          <span>⏱️ {metadata.processing_time}ms</span>
        )}
        {metadata.tokens_used && (
          <span>🔤 {metadata.tokens_used} tokens</span>
        )}
        {metadata.tools_used && metadata.tools_used.length > 0 && (
          <span>🔧 {metadata.tools_used.join(', ')}</span>
        )}
      </div>
    </div>
  );
}

function LoadingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="bg-gray-50 p-3 rounded-lg">
        <div className="flex items-center gap-2 text-gray-600">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Agent is thinking...</span>
        </div>
      </div>
    </div>
  );
}

// Multi-Agent Dashboard Component
export function MultiAgentDashboard() {
  const [agents, setAgents] = useState<AgentStatus[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  useEffect(() => {
    // Fetch agent statuses
    const fetchAgentStatuses = async () => {
      try {
        const response = await fetch('/api/agents/status');
        const agentData = await response.json();
        setAgents(agentData);
      } catch (error) {
        console.error('Error fetching agent statuses:', error);
      }
    };

    fetchAgentStatuses();
    const interval = setInterval(fetchAgentStatuses, 5000); // Update every 5 seconds

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-3xl font-bold">🤖 Multi-Agent Control Center</h1>
      
      {/* Agent Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((agent) => (
          <AgentCard 
            key={agent.id} 
            agent={agent} 
            onSelect={() => setSelectedAgent(agent.id)}
            isSelected={selectedAgent === agent.id}
          />
        ))}
      </div>

      {/* Selected Agent Details */}
      {selectedAgent && (
        <Card>
          <CardHeader>
            <CardTitle>Agent Details: {selectedAgent}</CardTitle>
          </CardHeader>
          <CardContent>
            <AgentChatInterface agentId={selectedAgent} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function AgentCard({ agent, onSelect, isSelected }: { 
  agent: AgentStatus; 
  onSelect: () => void;
  isSelected: boolean;
}) {
  return (
    <Card 
      className={`cursor-pointer transition-all hover:shadow-md ${
        isSelected ? 'ring-2 ring-blue-500' : ''
      }`}
      onClick={onSelect}
    >
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">{agent.name}</CardTitle>
          <AgentStatusBadge status={agent.status} />
        </div>
      </CardHeader>
      <CardContent>
        {agent.current_task && (
          <p className="text-sm text-muted-foreground mb-2">
            {agent.current_task}
          </p>
        )}
        {agent.progress !== undefined && (
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div 
              className="bg-blue-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${agent.progress}%` }}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

---

## Mental Model: Thinking Collaborative Interfaces

### Build the Mental Model: From Command to Collaboration

Think of the evolution from traditional UIs to agentic UIs like the difference between **operating machinery vs collaborating with a colleague**:

**Traditional UI (Operating Machinery)**:
- **Direct control**: Every action requires explicit input
- **Immediate feedback**: Results appear instantly
- **Predictable**: Same input always produces same output
- **Synchronous**: User waits for each operation to complete

**Agentic UI (Collaborating with Colleague)**:
- **Guided autonomy**: Set goals, agent determines methods
- **Asynchronous updates**: Progress reports during long tasks
- **Adaptive**: Agent adjusts approach based on context
- **Transparent**: Agent explains reasoning and actions

### Why It's Designed This Way: Supporting Trust and Control

Agentic UIs must balance agent autonomy with human oversight:

1. **Transparency**: Show what the agent is doing and why
2. **Control**: Provide mechanisms for intervention and guidance
3. **Trust**: Build confidence through consistent, explainable behavior
4. **Efficiency**: Minimize human cognitive load while maintaining oversight

### Further Exploration: Advanced UI Patterns

**Immediate Practice:**
1. Build a Chainlit interface with streaming responses and tool visualization
2. Create a Streamlit dashboard for multi-agent monitoring
3. Implement React components for real-time agent collaboration
4. Add guardrails and human-in-the-loop controls

**Design Challenge:**
Create an "agent collaboration workspace" where:
- Multiple agents work on complex projects together
- Humans can observe and guide the collaboration
- Progress is visualized in real-time
- Results are presented with full provenance and reasoning

**Advanced Exploration:**
- How would you implement voice interfaces for agent control?
- What patterns support collaborative editing between humans and agents?
- How could you visualize complex agent reasoning chains?
- What accessibility patterns ensure agentic UIs work for all users?

---

*Advanced agentic UI patterns transform the relationship between humans and AI from command-and-control to collaboration and oversight. These interfaces enable effective human-agent partnerships by providing transparency, control, and trust while supporting the autonomous capabilities that make agents powerful. Understanding these patterns is essential for building production agentic systems that users can confidently rely on.*