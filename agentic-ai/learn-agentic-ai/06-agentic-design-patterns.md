# Agentic Design Patterns: Architectural Blueprints for Autonomous AI Systems

**Based on:** [04_design_patterns](https://github.com/panaversity/learn-agentic-ai/tree/bd868a5030d29df4d816c9d6322899655424b49a/04_design_patterns)

## The Core Concept: Why This Example Exists

### The Problem: From Individual Agents to Coordinated Intelligence

Building a single autonomous agent is challenging enough, but real-world applications require **orchestrated systems** where multiple specialized agents work together to solve complex problems. Without established architectural patterns, developers often create:

- **Monolithic agents** that try to do everything, leading to poor performance and maintenance issues
- **Ad-hoc coordination** between agents that is brittle and hard to debug
- **Inefficient workflows** that don't leverage the strengths of different agent types
- **Unpredictable behavior** when agents interact in unexpected ways

The fundamental challenge is creating **systematic architectural patterns** that enable reliable, scalable, and maintainable multi-agent systems.

### The Solution: Proven Design Patterns for Agentic Systems

Design patterns in agentic AI serve the same purpose as architectural patterns in software engineering—they provide **tested, reusable solutions** to common problems. These patterns fall into three categories:

1. **Core Agentic Patterns** - Fundamental autonomous behaviors (Reflection, Tool Use, Planning, MultiAgent)
2. **Anthropic Workflow Patterns** - Structured approaches to complex tasks (Prompt Chaining, Routing, Parallelization, Orchestrator-Workers, Evaluator-Optimizer)
3. **Multi-Agent Architectures** - Organizational structures for agent collaboration (Hierarchical, Network, Sequential, Human-in-the-Loop)

The key insight: **Just as software architecture patterns enable building complex systems from simple components, agentic design patterns enable building sophisticated autonomous systems from individual agents.**

---

## Practical Walkthrough: Code Breakdown

### Category 1: Core Agentic Patterns - Fundamental Autonomous Behaviors

These patterns represent the essential capabilities that make AI systems truly autonomous.

#### 1. Reflection Pattern: Self-Improvement Through Iteration

**The Problem**: Agents produce outputs but can't evaluate or improve their own work.

**Implementation:**
```python
from agents import Agent, Runner
from typing import Dict, Any

class ReflectionAgent(Agent):
    def __init__(self):
        super().__init__(
            name="Reflective Writer",
            instructions="""You are a skilled writer who can evaluate and improve your own work.
            When given a task, first generate content, then critically evaluate it, and finally revise it."""
        )
    
    async def reflect_and_improve(self, task: str, max_iterations: int = 3) -> Dict[str, Any]:
        """Generate content with iterative self-improvement"""
        
        current_output = ""
        reflection_history = []
        
        for iteration in range(max_iterations):
            # Generate or revise content
            if iteration == 0:
                prompt = f"Write content for: {task}"
            else:
                prompt = f"""
                Previous output: {current_output}
                Previous reflection: {reflection_history[-1]}
                
                Revise the content based on the reflection:
                """
            
            generation_result = await Runner.run(self, prompt)
            current_output = generation_result.final_output
            
            # Reflect on the output
            reflection_prompt = f"""
            Evaluate this content: {current_output}
            
            Consider:
            1. Clarity and coherence
            2. Completeness and accuracy
            3. Engagement and style
            4. Areas for improvement
            
            Provide specific feedback and suggestions for improvement.
            If the content is already excellent, indicate that no further revision is needed.
            """
            
            reflection_result = await Runner.run(self, reflection_prompt)
            reflection = reflection_result.final_output
            reflection_history.append(reflection)
            
            # Check if reflection indicates satisfaction
            if "no further revision" in reflection.lower() or "excellent" in reflection.lower():
                break
        
        return {
            "final_output": current_output,
            "iterations": iteration + 1,
            "reflection_history": reflection_history
        }

# Usage
reflective_agent = ReflectionAgent()
result = await reflective_agent.reflect_and_improve(
    "Write a compelling product description for a new fitness tracker"
)
```

**Key Benefits:**
- **Quality Improvement**: Iterative refinement leads to better outputs
- **Self-Correction**: Agents can identify and fix their own mistakes
- **Adaptability**: Works across different types of content and tasks

#### 2. Tool Use Pattern: Extending Agent Capabilities

**The Problem**: Agents are limited to their training data and can't access real-time information or perform actions in the world.

**Implementation:**
```python
from agents import Agent, function_tool
import requests
from datetime import datetime

@function_tool
def get_weather(location: str) -> str:
    """Get current weather information for a location"""
    # Simulated weather API call
    return f"Current weather in {location}: 22°C, partly cloudy"

@function_tool
def get_stock_price(symbol: str) -> str:
    """Get current stock price for a symbol"""
    # Simulated stock API call
    return f"Current price of {symbol}: $150.25 (+2.3%)"

@function_tool
def send_email(recipient: str, subject: str, body: str) -> str:
    """Send an email"""
    # Simulated email sending
    return f"Email sent to {recipient} with subject '{subject}'"

class ToolEnabledAgent(Agent):
    def __init__(self):
        super().__init__(
            name="Research Assistant",
            instructions="""You are a research assistant with access to real-time information.
            Use the available tools to gather current data and take actions as needed.
            Always explain what tools you're using and why.""",
            tools=[get_weather, get_stock_price, send_email]
        )
    
    async def research_and_report(self, query: str) -> str:
        """Research a topic and provide a comprehensive report"""
        
        analysis_prompt = f"""
        Analyze this query: {query}
        
        Determine what information you need and what tools should be used.
        Then use the appropriate tools to gather the information.
        Finally, compile everything into a comprehensive report.
        """
        
        result = await Runner.run(self, analysis_prompt)
        return result.final_output

# Usage
tool_agent = ToolEnabledAgent()
report = await tool_agent.research_and_report(
    "What's the weather like in New York and how are tech stocks performing today?"
)
```

#### 3. Planning Pattern: Dynamic Task Decomposition

**The Problem**: Complex tasks can't be completed in a single step and require strategic planning.

**Implementation:**
```python
from agents import Agent, Runner
from typing import List, Dict, Any
import asyncio

class PlanningAgent(Agent):
    def __init__(self):
        super().__init__(
            name="Project Planner",
            instructions="""You are a strategic planning agent that can break down complex tasks 
            into manageable subtasks, execute them, and adapt the plan as needed."""
        )
    
    async def plan_and_execute(self, goal: str) -> Dict[str, Any]:
        """Plan and execute a complex task"""
        
        # Phase 1: Initial Planning
        planning_prompt = f"""
        Goal: {goal}
        
        Break this goal into specific, actionable subtasks.
        For each subtask, specify:
        1. What needs to be done
        2. What success looks like
        3. Any dependencies on other subtasks
        
        Return a structured plan with numbered subtasks.
        """
        
        planning_result = await Runner.run(self, planning_prompt)
        initial_plan = planning_result.final_output
        
        # Phase 2: Execute subtasks
        completed_tasks = []
        failed_tasks = []
        
        # Extract subtasks (simplified - in practice, you'd parse the plan)
        subtasks = self.extract_subtasks(initial_plan)
        
        for subtask in subtasks:
            try:
                # Execute the subtask
                execution_result = await Runner.run(
                    self, 
                    f"Execute this subtask: {subtask}\n\nPrevious completed tasks: {completed_tasks}"
                )
                
                # Test the result
                test_prompt = f"""
                Subtask: {subtask}
                Result: {execution_result.final_output}
                
                Evaluate if this subtask was completed successfully.
                If not, explain what went wrong and what needs to be adjusted.
                """
                
                test_result = await Runner.run(self, test_prompt)
                
                if "successful" in test_result.final_output.lower():
                    completed_tasks.append({
                        "subtask": subtask,
                        "result": execution_result.final_output
                    })
                else:
                    failed_tasks.append({
                        "subtask": subtask,
                        "result": execution_result.final_output,
                        "issue": test_result.final_output
                    })
                    
                    # Replan if needed
                    if failed_tasks:
                        replan_prompt = f"""
                        Original goal: {goal}
                        Failed subtask: {subtask}
                        Issue: {test_result.final_output}
                        Completed tasks: {completed_tasks}
                        
                        Adjust the plan to address the failed subtask.
                        What should we do differently?
                        """
                        
                        replan_result = await Runner.run(self, replan_prompt)
                        # In practice, you'd parse and integrate the new plan
                        
            except Exception as e:
                failed_tasks.append({
                    "subtask": subtask,
                    "error": str(e)
                })
        
        return {
            "goal": goal,
            "initial_plan": initial_plan,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "success_rate": len(completed_tasks) / len(subtasks) if subtasks else 0
        }
    
    def extract_subtasks(self, plan: str) -> List[str]:
        """Extract subtasks from the plan (simplified implementation)"""
        # In practice, you'd use more sophisticated parsing
        lines = plan.split('\n')
        subtasks = []
        for line in lines:
            if line.strip().startswith(('1.', '2.', '3.', '4.', '5.')):
                subtasks.append(line.strip())
        return subtasks

# Usage
planner = PlanningAgent()
result = await planner.plan_and_execute(
    "Organize a successful product launch event for our new software"
)
```

#### 4. MultiAgent Pattern: Collaborative Specialization

**The Problem**: Different tasks require different expertise, and no single agent can be optimal for all domains.

**Implementation:**
```python
from agents import Agent, Runner
from typing import Dict, Any, List

class SpecialistAgent(Agent):
    def __init__(self, name: str, expertise: str, instructions: str):
        super().__init__(
            name=name,
            instructions=f"You are a {expertise} specialist. {instructions}"
        )
        self.expertise = expertise

class MultiAgentSystem:
    def __init__(self):
        self.agents = {
            "researcher": SpecialistAgent(
                name="Research Specialist",
                expertise="research",
                instructions="Gather and analyze information from various sources. Focus on accuracy and comprehensiveness."
            ),
            "writer": SpecialistAgent(
                name="Content Writer",
                expertise="writing",
                instructions="Create engaging, well-structured content. Focus on clarity and audience engagement."
            ),
            "analyst": SpecialistAgent(
                name="Data Analyst",
                expertise="analysis",
                instructions="Analyze data and trends. Provide insights and actionable recommendations."
            ),
            "reviewer": SpecialistAgent(
                name="Quality Reviewer",
                expertise="review",
                instructions="Review work for quality, accuracy, and completeness. Provide constructive feedback."
            )
        }
    
    async def collaborative_project(self, project_description: str) -> Dict[str, Any]:
        """Execute a project using multiple specialized agents"""
        
        # Phase 1: Research
        research_prompt = f"""
        Project: {project_description}
        
        Conduct comprehensive research on this project.
        Identify key information, data sources, and relevant findings.
        """
        
        research_result = await Runner.run(self.agents["researcher"], research_prompt)
        
        # Phase 2: Analysis
        analysis_prompt = f"""
        Project: {project_description}
        Research findings: {research_result.final_output}
        
        Analyze the research findings and identify key insights, trends, and patterns.
        Provide actionable recommendations based on your analysis.
        """
        
        analysis_result = await Runner.run(self.agents["analyst"], analysis_prompt)
        
        # Phase 3: Content Creation
        writing_prompt = f"""
        Project: {project_description}
        Research: {research_result.final_output}
        Analysis: {analysis_result.final_output}
        
        Create comprehensive content that incorporates the research findings and analysis.
        Make it engaging and appropriate for the target audience.
        """
        
        writing_result = await Runner.run(self.agents["writer"], writing_prompt)
        
        # Phase 4: Review
        review_prompt = f"""
        Project: {project_description}
        Final content: {writing_result.final_output}
        
        Review the content for:
        1. Accuracy and completeness
        2. Clarity and engagement
        3. Alignment with project goals
        4. Areas for improvement
        
        Provide specific feedback and suggestions.
        """
        
        review_result = await Runner.run(self.agents["reviewer"], review_prompt)
        
        return {
            "project": project_description,
            "research": research_result.final_output,
            "analysis": analysis_result.final_output,
            "content": writing_result.final_output,
            "review": review_result.final_output,
            "agents_used": list(self.agents.keys())
        }

# Usage
multi_agent_system = MultiAgentSystem()
result = await multi_agent_system.collaborative_project(
    "Create a comprehensive market analysis report for electric vehicles in 2024"
)
```

### Category 2: Anthropic Workflow Patterns - Structured Task Orchestration

These patterns provide structured approaches to complex tasks with predictable workflows.

#### 1. Prompt Chaining: Sequential Task Processing

**Sequential processing where each step builds on the previous:**

```python
from agents import Agent, Runner
from typing import List, Dict, Any

class PromptChainOrchestrator:
    def __init__(self):
        self.agent = Agent(
            name="Chain Processor",
            instructions="Process tasks in sequence, using previous outputs as context for next steps."
        )
    
    async def execute_chain(self, initial_input: str, chain_steps: List[Dict[str, str]]) -> Dict[str, Any]:
        """Execute a sequence of prompts where each builds on the previous"""
        
        current_input = initial_input
        results = []
        
        for i, step in enumerate(chain_steps):
            step_prompt = f"""
            Step {i+1}: {step['description']}
            
            Input: {current_input}
            
            Task: {step['task']}
            """
            
            result = await Runner.run(self.agent, step_prompt)
            current_input = result.final_output
            
            results.append({
                "step": i+1,
                "description": step['description'],
                "output": result.final_output
            })
        
        return {
            "initial_input": initial_input,
            "final_output": current_input,
            "steps": results
        }

# Usage
chain_orchestrator = PromptChainOrchestrator()
marketing_chain = await chain_orchestrator.execute_chain(
    "New fitness tracking app called 'FitTrack Pro'",
    [
        {
            "description": "Generate product description",
            "task": "Create a compelling product description highlighting key features and benefits"
        },
        {
            "description": "Create marketing copy",
            "task": "Transform the product description into engaging marketing copy for social media"
        },
        {
            "description": "Translate to Spanish",
            "task": "Translate the marketing copy to Spanish for international markets"
        }
    ]
)
```

#### 2. Routing: Intelligent Task Distribution

**Directing tasks to appropriate specialized handlers:**

```python
from agents import Agent, Runner
from typing import Dict, Any

class RoutingOrchestrator:
    def __init__(self):
        self.classifier = Agent(
            name="Task Classifier",
            instructions="Classify incoming tasks and route them to appropriate handlers."
        )
        
        self.handlers = {
            "technical": Agent(
                name="Technical Support",
                instructions="Handle technical issues and provide solutions."
            ),
            "billing": Agent(
                name="Billing Support", 
                instructions="Handle billing inquiries and payment issues."
            ),
            "general": Agent(
                name="General Support",
                instructions="Handle general inquiries and provide information."
            )
        }
    
    async def route_and_process(self, user_query: str) -> Dict[str, Any]:
        """Route user query to appropriate handler"""
        
        # Classification step
        classification_prompt = f"""
        User query: {user_query}
        
        Classify this query into one of these categories:
        - technical: Issues with product functionality, bugs, or technical problems
        - billing: Questions about payments, invoices, or account billing
        - general: General information requests, basic questions
        
        Return only the category name.
        """
        
        classification_result = await Runner.run(self.classifier, classification_prompt)
        category = classification_result.final_output.strip().lower()
        
        # Route to appropriate handler
        if category in self.handlers:
            handler = self.handlers[category]
            response = await Runner.run(handler, user_query)
            
            return {
                "query": user_query,
                "category": category,
                "handler": handler.name,
                "response": response.final_output
            }
        else:
            # Default to general handler
            handler = self.handlers["general"]
            response = await Runner.run(handler, user_query)
            
            return {
                "query": user_query,
                "category": "general",
                "handler": handler.name,
                "response": response.final_output
            }

# Usage
router = RoutingOrchestrator()
result = await router.route_and_process(
    "I can't log into my account and my password reset isn't working"
)
```

#### 3. Orchestrator-Workers: Hierarchical Task Management

**Central orchestrator managing multiple specialized workers:**

```python
from agents import Agent, Runner
from typing import List, Dict, Any
import asyncio

class OrchestratorWorkerSystem:
    def __init__(self):
        self.orchestrator = Agent(
            name="Project Orchestrator",
            instructions="""You are a project orchestrator that manages multiple specialized workers.
            Break down complex projects into subtasks and delegate them to appropriate workers.
            Synthesize the results into a coherent final output."""
        )
        
        self.workers = {
            "research": Agent(
                name="Research Worker",
                instructions="Conduct thorough research on assigned topics. Provide detailed findings."
            ),
            "design": Agent(
                name="Design Worker", 
                instructions="Create design concepts and visual elements. Focus on user experience."
            ),
            "content": Agent(
                name="Content Worker",
                instructions="Create written content, copy, and documentation. Ensure clarity and engagement."
            ),
            "analysis": Agent(
                name="Analysis Worker",
                instructions="Analyze data and provide insights. Focus on actionable recommendations."
            )
        }
    
    async def orchestrate_project(self, project_description: str) -> Dict[str, Any]:
        """Orchestrate a complex project using multiple workers"""
        
        # Orchestrator plans the work
        planning_prompt = f"""
        Project: {project_description}
        
        Available workers: {list(self.workers.keys())}
        
        Break this project into subtasks and assign each to the most appropriate worker.
        Format your response as:
        
        SUBTASK 1: [description]
        WORKER: [worker_name]
        
        SUBTASK 2: [description]
        WORKER: [worker_name]
        
        etc.
        """
        
        planning_result = await Runner.run(self.orchestrator, planning_prompt)
        
        # Parse the plan (simplified)
        subtasks = self.parse_work_plan(planning_result.final_output)
        
        # Execute subtasks in parallel
        worker_tasks = []
        for subtask in subtasks:
            worker = self.workers[subtask["worker"]]
            task = asyncio.create_task(
                Runner.run(worker, subtask["description"])
            )
            worker_tasks.append((subtask, task))
        
        # Collect results
        worker_results = []
        for subtask, task in worker_tasks:
            result = await task
            worker_results.append({
                "subtask": subtask["description"],
                "worker": subtask["worker"],
                "output": result.final_output
            })
        
        # Orchestrator synthesizes results
        synthesis_prompt = f"""
        Project: {project_description}
        
        Worker results:
        {chr(10).join([f"- {r['worker']}: {r['output']}" for r in worker_results])}
        
        Synthesize these results into a coherent final deliverable for the project.
        """
        
        synthesis_result = await Runner.run(self.orchestrator, synthesis_prompt)
        
        return {
            "project": project_description,
            "work_plan": planning_result.final_output,
            "worker_results": worker_results,
            "final_output": synthesis_result.final_output
        }
    
    def parse_work_plan(self, plan: str) -> List[Dict[str, str]]:
        """Parse work plan into subtasks (simplified implementation)"""
        subtasks = []
        lines = plan.split('\n')
        current_subtask = None
        
        for line in lines:
            line = line.strip()
            if line.startswith('SUBTASK'):
                current_subtask = {"description": line.split(':', 1)[1].strip()}
            elif line.startswith('WORKER') and current_subtask:
                worker_name = line.split(':', 1)[1].strip()
                if worker_name in self.workers:
                    current_subtask["worker"] = worker_name
                    subtasks.append(current_subtask)
                    current_subtask = None
        
        return subtasks

# Usage
orchestrator_system = OrchestratorWorkerSystem()
result = await orchestrator_system.orchestrate_project(
    "Create a comprehensive launch strategy for a new mobile productivity app"
)
```

---

## Mental Model: Thinking in Architectural Patterns

### Build the Mental Model: Patterns as Organizational Principles

Think of agentic design patterns like **organizational structures** in human teams:

**Single Agent Patterns:**
- **Reflection Pattern** = A professional who reviews and improves their own work
- **Tool Use Pattern** = A specialist who uses the right tools for each job
- **Planning Pattern** = A project manager who breaks down complex goals

**Multi-Agent Patterns:**
- **Hierarchical** = Traditional corporate structure with clear chain of command
- **Network** = Collaborative team where everyone talks to everyone
- **Sequential** = Assembly line where each person adds to the work
- **Orchestrator-Workers** = Conductor directing specialized musicians

### Why It's Designed This Way: Balancing Autonomy and Coordination

Each pattern represents a different solution to the fundamental tension between:

1. **Autonomy** (agents making independent decisions)
2. **Coordination** (agents working together effectively)
3. **Efficiency** (completing tasks with minimal overhead)
4. **Reliability** (predictable, debuggable behavior)

**Pattern Selection Criteria:**
- **Task Complexity**: Simple tasks → individual patterns; complex tasks → multi-agent patterns
- **Specialization Needs**: Broad tasks → general agents; specialized tasks → expert agents
- **Coordination Requirements**: Independent subtasks → parallel patterns; dependent subtasks → sequential patterns
- **Quality Requirements**: High quality → reflection patterns; speed → direct patterns

### Further Exploration: Building Production Systems

**Immediate Practice:**
1. Implement each pattern for a simple domain (e.g., content creation)
2. Compare performance and reliability across patterns
3. Combine patterns (e.g., Reflection + Tool Use)

**Design Challenge:**
Create a "smart home management system" that uses multiple patterns:
- **Routing** for handling different types of requests (lighting, temperature, security)
- **Planning** for complex routines (morning startup, evening shutdown)
- **Orchestrator-Workers** for coordinating multiple device controllers
- **Human-in-the-Loop** for security and privacy decisions

**Advanced Exploration:**
- How would you implement pattern composition (patterns within patterns)?
- What metrics would you use to evaluate pattern effectiveness?
- How could patterns adapt and evolve based on usage patterns?
- What new patterns might emerge as agents become more sophisticated?

---

*The design patterns you've learned here provide proven architectural solutions for building robust agentic systems. Understanding when and how to apply these patterns—from simple reflection loops to complex multi-agent orchestration—is essential for creating reliable, maintainable, and scalable autonomous AI systems. Next, we'll explore how to implement these patterns in production environments using agent-native development approaches.*