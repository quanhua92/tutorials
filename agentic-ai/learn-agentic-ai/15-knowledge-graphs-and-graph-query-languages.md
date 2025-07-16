# Knowledge Graphs and Graph Query Languages: Structured Knowledge for Intelligent Agents

**Based on:** [11_knowledge_graphs](https://github.com/panaversity/learn-agentic-ai/tree/bd868a5030d29df4d816c9d6322899655424b49a/11_knowledge_graphs)

## The Core Concept: Why This Example Exists

### The Problem: Unstructured Knowledge Limits Agent Intelligence

Traditional AI agents rely on **unstructured knowledge** embedded in their training data and vector embeddings, creating significant limitations:

- **Lack of Explicit Relationships**: Agents can't understand how entities relate to each other
- **Limited Reasoning Capabilities**: No logical inference over structured knowledge
- **Hallucination Issues**: Agents generate false information without grounded facts
- **Context Loss**: Important relationships and dependencies are lost in embeddings
- **Inefficient Knowledge Retrieval**: Vector similarity doesn't capture logical relationships
- **No Dynamic Knowledge Updates**: Static knowledge that can't grow or evolve

The fundamental challenge is providing agents with **structured, queryable knowledge** that enables sophisticated reasoning, inference, and decision-making.

### The Solution: Knowledge Graphs with Graph Query Languages

**Knowledge graphs** combined with **graph query languages** provide agents with structured, queryable knowledge that enables:

- **Explicit Relationship Modeling**: Clear representation of how entities connect and interact
- **Graph-Based Reasoning**: Logical inference through relationship traversal
- **Grounded Knowledge**: Facts anchored in structured, verifiable relationships
- **Contextual Understanding**: Rich context through multi-degree relationship exploration
- **Efficient Knowledge Retrieval**: Pattern-based querying for precise information
- **Dynamic Knowledge Evolution**: Real-time updates and learning from new information

The key insight: **Knowledge graphs transform agents from pattern-matching systems into reasoning systems that can understand, infer, and explain relationships in structured knowledge domains.**

---

## Practical Walkthrough: Code Breakdown

### Foundation Layer: Graph Database Integration with Neo4j

Neo4j provides the most mature graph database platform with Cypher query language support, transitioning toward the new GQL standard.

#### Agent-Powered Knowledge Graph System

**Neo4j Integration for Agent Knowledge:**
```python
from neo4j import GraphDatabase
from typing import Dict, List, Any, Optional
import json
from datetime import datetime
import asyncio

class AgentKnowledgeGraph:
    """Knowledge graph system for AI agents using Neo4j"""
    
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.agent_context = {}
        
    def close(self):
        """Close database connection"""
        self.driver.close()
    
    async def create_agent_knowledge_schema(self):
        """Create knowledge graph schema optimized for agent reasoning"""
        
        with self.driver.session() as session:
            # Create constraints and indexes for performance
            schema_queries = [
                # Entity constraints
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
                "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.id IS UNIQUE",
                
                # Relationship indexes
                "CREATE INDEX relationship_type IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.type)",
                "CREATE INDEX temporal_index IF NOT EXISTS FOR ()-[r:OCCURRED_AT]-() ON (r.timestamp)",
                
                # Agent-specific indexes
                "CREATE INDEX agent_query_index IF NOT EXISTS FOR (n:Entity) ON (n.name, n.type)",
                "CREATE INDEX knowledge_domain_index IF NOT EXISTS FOR (n) ON (n.domain, n.importance)"
            ]
            
            for query in schema_queries:
                try:
                    session.run(query)
                    print(f"✅ Schema created: {query[:50]}...")
                except Exception as e:
                    print(f"❌ Schema error: {e}")
    
    async def add_knowledge_entity(
        self,
        entity_id: str,
        entity_type: str,
        properties: Dict[str, Any],
        agent_source: str = None
    ) -> bool:
        """Add a knowledge entity with agent tracking"""
        
        with self.driver.session() as session:
            try:
                # Create entity with metadata
                entity_properties = {
                    **properties,
                    "id": entity_id,
                    "type": entity_type,
                    "created_at": datetime.now().isoformat(),
                    "created_by_agent": agent_source,
                    "confidence_score": properties.get("confidence", 1.0),
                    "importance": properties.get("importance", 0.5)
                }
                
                query = f"""
                MERGE (e:Entity {{id: $entity_id}})
                SET e += $properties
                SET e:` + entity_type + `
                RETURN e
                """
                
                result = session.run(query, entity_id=entity_id, properties=entity_properties)
                
                # Log the addition for agent learning
                await self._log_knowledge_change(
                    "entity_added",
                    {"entity_id": entity_id, "type": entity_type, "agent": agent_source}
                )
                
                return True
                
            except Exception as e:
                print(f"Error adding entity {entity_id}: {e}")
                return False
    
    async def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        properties: Dict[str, Any] = None,
        agent_source: str = None
    ) -> bool:
        """Add relationship between entities"""
        
        with self.driver.session() as session:
            try:
                rel_properties = {
                    **(properties or {}),
                    "created_at": datetime.now().isoformat(),
                    "created_by_agent": agent_source,
                    "confidence": properties.get("confidence", 1.0) if properties else 1.0
                }
                
                query = """
                MATCH (source:Entity {id: $source_id})
                MATCH (target:Entity {id: $target_id})
                MERGE (source)-[r:RELATES_TO {type: $rel_type}]->(target)
                SET r += $properties
                RETURN r
                """
                
                session.run(
                    query,
                    source_id=source_id,
                    target_id=target_id,
                    rel_type=relationship_type,
                    properties=rel_properties
                )
                
                await self._log_knowledge_change(
                    "relationship_added",
                    {
                        "source": source_id,
                        "target": target_id,
                        "type": relationship_type,
                        "agent": agent_source
                    }
                )
                
                return True
                
            except Exception as e:
                print(f"Error adding relationship: {e}")
                return False
    
    async def query_knowledge(
        self,
        query_type: str,
        parameters: Dict[str, Any],
        agent_id: str = None
    ) -> List[Dict[str, Any]]:
        """Query knowledge graph for agent reasoning"""
        
        with self.driver.session() as session:
            try:
                if query_type == "find_related_entities":
                    return await self._find_related_entities(session, parameters)
                elif query_type == "find_path":
                    return await self._find_path_between_entities(session, parameters)
                elif query_type == "get_entity_context":
                    return await self._get_entity_context(session, parameters)
                elif query_type == "discover_patterns":
                    return await self._discover_patterns(session, parameters)
                elif query_type == "reasoning_chain":
                    return await self._build_reasoning_chain(session, parameters)
                else:
                    raise ValueError(f"Unknown query type: {query_type}")
                    
            except Exception as e:
                print(f"Error querying knowledge: {e}")
                return []
    
    async def _find_related_entities(
        self,
        session,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Find entities related to a given entity"""
        
        entity_id = params["entity_id"]
        max_depth = params.get("max_depth", 2)
        relationship_types = params.get("relationship_types", [])
        
        # Build dynamic query based on parameters
        rel_filter = ""
        if relationship_types:
            rel_filter = f"AND r.type IN {relationship_types}"
        
        query = f"""
        MATCH (start:Entity {{id: $entity_id}})
        MATCH (start)-[r:RELATES_TO*1..{max_depth}]-(related:Entity)
        WHERE 1=1 {rel_filter}
        RETURN DISTINCT related.id as entity_id,
               related.name as name,
               related.type as type,
               r[-1].type as relationship_type,
               r[-1].confidence as confidence,
               length(r) as distance
        ORDER BY distance, confidence DESC
        LIMIT 50
        """
        
        result = session.run(query, entity_id=entity_id)
        
        return [
            {
                "entity_id": record["entity_id"],
                "name": record["name"],
                "type": record["type"],
                "relationship_type": record["relationship_type"],
                "confidence": record["confidence"],
                "distance": record["distance"]
            }
            for record in result
        ]
    
    async def _find_path_between_entities(
        self,
        session,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Find reasoning path between two entities"""
        
        source_id = params["source_id"]
        target_id = params["target_id"]
        max_depth = params.get("max_depth", 4)
        
        query = f"""
        MATCH (source:Entity {{id: $source_id}})
        MATCH (target:Entity {{id: $target_id}})
        MATCH path = shortestPath((source)-[r:RELATES_TO*1..{max_depth}]-(target))
        RETURN [node in nodes(path) | {{
            id: node.id,
            name: node.name,
            type: node.type
        }}] as nodes,
        [rel in relationships(path) | {{
            type: rel.type,
            confidence: rel.confidence
        }}] as relationships,
        length(path) as path_length
        ORDER BY path_length
        LIMIT 5
        """
        
        result = session.run(query, source_id=source_id, target_id=target_id)
        
        return [
            {
                "nodes": record["nodes"],
                "relationships": record["relationships"],
                "path_length": record["path_length"],
                "reasoning_strength": self._calculate_path_confidence(record["relationships"])
            }
            for record in result
        ]
    
    async def _get_entity_context(
        self,
        session,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get comprehensive context for an entity"""
        
        entity_id = params["entity_id"]
        context_depth = params.get("context_depth", "comprehensive")
        
        if context_depth == "basic":
            query = """
            MATCH (e:Entity {id: $entity_id})
            OPTIONAL MATCH (e)-[r:RELATES_TO]-(related:Entity)
            RETURN e as entity,
                   collect(DISTINCT {
                       entity: related.name,
                       relationship: r.type,
                       confidence: r.confidence
                   }) as direct_relationships
            """
        else:  # comprehensive
            query = """
            MATCH (e:Entity {id: $entity_id})
            OPTIONAL MATCH (e)-[r1:RELATES_TO]-(level1:Entity)
            OPTIONAL MATCH (level1)-[r2:RELATES_TO]-(level2:Entity)
            WHERE level2.id <> e.id
            
            RETURN e as entity,
                   collect(DISTINCT {
                       entity: level1.name,
                       relationship: r1.type,
                       confidence: r1.confidence,
                       distance: 1
                   }) as level1_relationships,
                   collect(DISTINCT {
                       entity: level2.name,
                       relationship: r2.type,
                       confidence: r2.confidence,
                       distance: 2,
                       through: level1.name
                   }) as level2_relationships
            """
        
        result = session.run(query, entity_id=entity_id)
        
        return [dict(record) for record in result]
    
    async def _discover_patterns(
        self,
        session,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Discover patterns in the knowledge graph"""
        
        pattern_type = params.get("pattern_type", "common_structures")
        min_frequency = params.get("min_frequency", 3)
        
        if pattern_type == "common_structures":
            # Find common structural patterns
            query = """
            MATCH (a:Entity)-[r1:RELATES_TO]->(b:Entity)-[r2:RELATES_TO]->(c:Entity)
            WHERE a.id <> c.id
            WITH r1.type as rel1, r2.type as rel2, count(*) as frequency
            WHERE frequency >= $min_frequency
            RETURN rel1, rel2, frequency
            ORDER BY frequency DESC
            LIMIT 20
            """
        elif pattern_type == "influential_entities":
            # Find entities with high centrality
            query = """
            MATCH (e:Entity)
            OPTIONAL MATCH (e)-[r:RELATES_TO]-(other:Entity)
            WITH e, count(r) as connections
            WHERE connections > $min_frequency
            RETURN e.id as entity_id,
                   e.name as name,
                   e.type as type,
                   connections,
                   e.importance as importance_score
            ORDER BY connections DESC, importance_score DESC
            LIMIT 20
            """
        
        result = session.run(query, min_frequency=min_frequency)
        return [dict(record) for record in result]
    
    async def _build_reasoning_chain(
        self,
        session,
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Build a reasoning chain for agent decision-making"""
        
        start_concept = params["start_concept"]
        goal_concept = params["goal_concept"]
        reasoning_type = params.get("reasoning_type", "causal")
        
        if reasoning_type == "causal":
            # Find causal reasoning chains
            query = """
            MATCH (start:Entity {name: $start_concept})
            MATCH (goal:Entity {name: $goal_concept})
            MATCH path = (start)-[r:RELATES_TO*1..5]-(goal)
            WHERE ALL(rel in relationships(path) WHERE rel.type IN ['CAUSES', 'LEADS_TO', 'INFLUENCES'])
            
            RETURN [node in nodes(path) | {
                id: node.id,
                name: node.name,
                type: node.type
            }] as reasoning_chain,
            [rel in relationships(path) | {
                type: rel.type,
                confidence: rel.confidence,
                strength: rel.strength
            }] as reasoning_links,
            reduce(conf = 1.0, rel in relationships(path) | conf * rel.confidence) as chain_confidence
            ORDER BY chain_confidence DESC
            LIMIT 5
            """
        elif reasoning_type == "associative":
            # Find associative reasoning chains
            query = """
            MATCH (start:Entity {name: $start_concept})
            MATCH (goal:Entity {name: $goal_concept})
            MATCH path = (start)-[r:RELATES_TO*1..4]-(goal)
            WHERE ALL(rel in relationships(path) WHERE rel.type IN ['SIMILAR_TO', 'CATEGORY_OF', 'RELATED_TO'])
            
            RETURN [node in nodes(path) | {
                id: node.id,
                name: node.name,
                type: node.type
            }] as reasoning_chain,
            [rel in relationships(path) | {
                type: rel.type,
                confidence: rel.confidence
            }] as reasoning_links,
            length(path) as chain_length
            ORDER BY chain_length, reduce(conf = 1.0, rel in relationships(path) | conf * rel.confidence) DESC
            LIMIT 5
            """
        
        result = session.run(
            query,
            start_concept=start_concept,
            goal_concept=goal_concept
        )
        
        return [dict(record) for record in result]
    
    def _calculate_path_confidence(self, relationships: List[Dict[str, Any]]) -> float:
        """Calculate confidence score for a reasoning path"""
        if not relationships:
            return 0.0
        
        # Multiply confidences (weakest link determines overall strength)
        confidence = 1.0
        for rel in relationships:
            confidence *= rel.get("confidence", 1.0)
        
        return confidence
    
    async def _log_knowledge_change(self, change_type: str, details: Dict[str, Any]):
        """Log knowledge graph changes for agent learning"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "change_type": change_type,
            "details": details
        }
        
        # In production, store in separate audit table
        print(f"📝 Knowledge change: {change_type} - {details}")

class AgentKnowledgeInterface:
    """High-level interface for agents to interact with knowledge graphs"""
    
    def __init__(self, knowledge_graph: AgentKnowledgeGraph, agent_id: str):
        self.kg = knowledge_graph
        self.agent_id = agent_id
        self.query_history = []
        
    async def ask_knowledge_question(self, question: str) -> Dict[str, Any]:
        """Natural language interface to knowledge graph queries"""
        
        # Parse natural language question into graph query
        query_intent = await self._parse_question_intent(question)
        
        # Execute appropriate graph query
        results = await self.kg.query_knowledge(
            query_intent["query_type"],
            query_intent["parameters"],
            self.agent_id
        )
        
        # Format results for agent consumption
        formatted_response = await self._format_knowledge_response(
            question,
            query_intent,
            results
        )
        
        # Track query for learning
        self.query_history.append({
            "question": question,
            "intent": query_intent,
            "results_count": len(results),
            "timestamp": datetime.now().isoformat()
        })
        
        return formatted_response
    
    async def _parse_question_intent(self, question: str) -> Dict[str, Any]:
        """Parse natural language question into graph query parameters"""
        
        question_lower = question.lower()
        
        # Simple intent classification (in production, use NLP models)
        if "related to" in question_lower or "connected to" in question_lower:
            entity_name = self._extract_entity_name(question)
            return {
                "query_type": "find_related_entities",
                "parameters": {
                    "entity_id": entity_name,
                    "max_depth": 2
                }
            }
        
        elif "path between" in question_lower or "connection between" in question_lower:
            entities = self._extract_two_entities(question)
            return {
                "query_type": "find_path",
                "parameters": {
                    "source_id": entities[0],
                    "target_id": entities[1],
                    "max_depth": 4
                }
            }
        
        elif "what is" in question_lower or "tell me about" in question_lower:
            entity_name = self._extract_entity_name(question)
            return {
                "query_type": "get_entity_context",
                "parameters": {
                    "entity_id": entity_name,
                    "context_depth": "comprehensive"
                }
            }
        
        elif "patterns" in question_lower or "common" in question_lower:
            return {
                "query_type": "discover_patterns",
                "parameters": {
                    "pattern_type": "common_structures",
                    "min_frequency": 3
                }
            }
        
        else:
            # Default to entity context
            entity_name = self._extract_entity_name(question)
            return {
                "query_type": "get_entity_context",
                "parameters": {
                    "entity_id": entity_name,
                    "context_depth": "basic"
                }
            }
    
    def _extract_entity_name(self, question: str) -> str:
        """Extract entity name from question (simplified)"""
        # In production, use NER models
        import re
        
        # Look for quoted entities
        quoted = re.findall(r'"([^"]*)"', question)
        if quoted:
            return quoted[0]
        
        # Look for capitalized words
        words = question.split()
        capitalized = [word for word in words if word[0].isupper() and word.isalpha()]
        if capitalized:
            return capitalized[0]
        
        # Fallback to last noun-like word
        return words[-1] if words else "unknown"
    
    def _extract_two_entities(self, question: str) -> List[str]:
        """Extract two entities for relationship queries"""
        # Simplified extraction
        words = question.split()
        capitalized = [word for word in words if word[0].isupper() and word.isalpha()]
        
        if len(capitalized) >= 2:
            return [capitalized[0], capitalized[1]]
        else:
            return ["entity1", "entity2"]  # Fallback
    
    async def _format_knowledge_response(
        self,
        original_question: str,
        query_intent: Dict[str, Any],
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Format knowledge graph results for agent consumption"""
        
        if not results:
            return {
                "question": original_question,
                "answer": "No relevant information found in knowledge graph.",
                "confidence": 0.0,
                "knowledge_source": "graph_database",
                "results_count": 0
            }
        
        query_type = query_intent["query_type"]
        
        if query_type == "find_related_entities":
            answer = self._format_related_entities_response(results)
        elif query_type == "find_path":
            answer = self._format_path_response(results)
        elif query_type == "get_entity_context":
            answer = self._format_context_response(results)
        elif query_type == "discover_patterns":
            answer = self._format_patterns_response(results)
        else:
            answer = f"Found {len(results)} results in knowledge graph."
        
        # Calculate overall confidence
        confidence = self._calculate_response_confidence(results, query_type)
        
        return {
            "question": original_question,
            "answer": answer,
            "confidence": confidence,
            "knowledge_source": "graph_database",
            "results_count": len(results),
            "query_intent": query_intent,
            "structured_results": results
        }
    
    def _format_related_entities_response(self, results: List[Dict[str, Any]]) -> str:
        """Format related entities into natural language"""
        
        if not results:
            return "No related entities found."
        
        # Group by relationship type
        by_relationship = {}
        for result in results:
            rel_type = result["relationship_type"]
            if rel_type not in by_relationship:
                by_relationship[rel_type] = []
            by_relationship[rel_type].append(result["name"])
        
        # Create natural language description
        descriptions = []
        for rel_type, entities in by_relationship.items():
            entity_list = ", ".join(entities[:5])  # Limit to 5 per type
            descriptions.append(f"{rel_type.replace('_', ' ').title()}: {entity_list}")
        
        return "Related entities found:\n" + "\n".join(descriptions)
    
    def _format_path_response(self, results: List[Dict[str, Any]]) -> str:
        """Format reasoning paths into natural language"""
        
        if not results:
            return "No reasoning path found between the entities."
        
        best_path = results[0]  # Assuming sorted by confidence
        nodes = best_path["nodes"]
        relationships = best_path["relationships"]
        
        # Build reasoning chain description
        chain_parts = []
        for i in range(len(nodes) - 1):
            source = nodes[i]["name"]
            target = nodes[i + 1]["name"]
            rel_type = relationships[i]["type"].replace("_", " ").lower()
            
            chain_parts.append(f"{source} {rel_type} {target}")
        
        reasoning_chain = " → ".join(chain_parts)
        confidence = best_path.get("reasoning_strength", 0.0)
        
        return f"Reasoning path (confidence: {confidence:.2f}):\n{reasoning_chain}"
    
    def _format_context_response(self, results: List[Dict[str, Any]]) -> str:
        """Format entity context into natural language"""
        
        if not results:
            return "No context information found for this entity."
        
        context_data = results[0]
        entity = context_data["entity"]
        
        response = f"**{entity.get('name', 'Unknown Entity')}** ({entity.get('type', 'Entity')})\n\n"
        
        # Add direct relationships
        if "direct_relationships" in context_data:
            relationships = context_data["direct_relationships"]
            if relationships:
                response += "Direct relationships:\n"
                for rel in relationships[:10]:  # Limit to 10
                    response += f"- {rel['relationship'].replace('_', ' ').title()}: {rel['entity']}\n"
        
        return response
    
    def _calculate_response_confidence(
        self, 
        results: List[Dict[str, Any]], 
        query_type: str
    ) -> float:
        """Calculate confidence score for the response"""
        
        if not results:
            return 0.0
        
        if query_type == "find_path":
            # Use reasoning strength from path results
            return max(result.get("reasoning_strength", 0.0) for result in results)
        elif query_type == "find_related_entities":
            # Average confidence of relationships
            confidences = [result.get("confidence", 1.0) for result in results]
            return sum(confidences) / len(confidences)
        else:
            # Default confidence based on result count
            return min(1.0, len(results) / 10.0)

# Usage example integrating with agents
class KnowledgeEnhancedAgent:
    """AI Agent enhanced with knowledge graph capabilities"""
    
    def __init__(self, agent_name: str, kg_interface: AgentKnowledgeInterface):
        self.agent_name = agent_name
        self.kg_interface = kg_interface
        self.reasoning_memory = []
        
    async def process_query_with_knowledge(self, user_query: str) -> Dict[str, Any]:
        """Process user query using both LLM and knowledge graph"""
        
        # Step 1: Extract key entities and concepts from user query
        key_entities = await self._extract_key_entities(user_query)
        
        # Step 2: Query knowledge graph for each entity
        knowledge_context = []
        for entity in key_entities:
            kg_response = await self.kg_interface.ask_knowledge_question(
                f"What is related to {entity}?"
            )
            knowledge_context.append(kg_response)
        
        # Step 3: Build reasoning chain if multiple entities
        if len(key_entities) >= 2:
            reasoning_chain = await self.kg_interface.ask_knowledge_question(
                f"What is the path between {key_entities[0]} and {key_entities[1]}?"
            )
            knowledge_context.append(reasoning_chain)
        
        # Step 4: Synthesize LLM response with knowledge graph context
        enhanced_response = await self._synthesize_response(
            user_query,
            knowledge_context
        )
        
        # Step 5: Update knowledge graph with new insights
        await self._update_knowledge_from_interaction(
            user_query,
            enhanced_response,
            knowledge_context
        )
        
        return {
            "query": user_query,
            "response": enhanced_response,
            "knowledge_context": knowledge_context,
            "reasoning_confidence": self._calculate_overall_confidence(knowledge_context),
            "entities_used": key_entities
        }
    
    async def _extract_key_entities(self, query: str) -> List[str]:
        """Extract key entities from user query"""
        # Simplified entity extraction (in production, use NER models)
        import re
        
        # Find capitalized words and quoted phrases
        entities = []
        
        # Quoted phrases
        quoted = re.findall(r'"([^"]*)"', query)
        entities.extend(quoted)
        
        # Capitalized words
        words = query.split()
        capitalized = [word for word in words if word[0].isupper() and word.isalpha()]
        entities.extend(capitalized)
        
        # Remove duplicates and return
        return list(set(entities))
    
    async def _synthesize_response(
        self,
        user_query: str,
        knowledge_context: List[Dict[str, Any]]
    ) -> str:
        """Synthesize response using LLM + knowledge graph context"""
        
        # Build context prompt with knowledge graph information
        context_prompt = f"""
        User Question: {user_query}
        
        Knowledge Graph Context:
        """
        
        for i, kg_response in enumerate(knowledge_context):
            context_prompt += f"\n{i+1}. {kg_response['answer']}"
            if kg_response.get('confidence', 0) > 0.8:
                context_prompt += " (high confidence)"
        
        context_prompt += f"""
        
        Instructions:
        - Use the knowledge graph context to provide accurate, grounded information
        - Indicate when information comes from the knowledge graph vs general knowledge
        - If the knowledge graph provides contradictory information, mention the uncertainty
        - Explain your reasoning process using the structured knowledge
        
        Provide a comprehensive response that leverages both the structured knowledge and your general understanding.
        """
        
        # In production, call actual LLM API here
        # For demo, return structured response
        return f"""
        Based on the knowledge graph analysis:
        
        {self._create_synthesized_answer(user_query, knowledge_context)}
        
        This response is grounded in structured knowledge relationships with confidence scores ranging from {min(kg['confidence'] for kg in knowledge_context):.2f} to {max(kg['confidence'] for kg in knowledge_context):.2f}.
        """
    
    def _create_synthesized_answer(
        self, 
        query: str, 
        knowledge_context: List[Dict[str, Any]]
    ) -> str:
        """Create synthesized answer from knowledge context"""
        
        # Extract high-confidence facts
        high_conf_facts = [
            kg['answer'] for kg in knowledge_context 
            if kg.get('confidence', 0) > 0.7
        ]
        
        if high_conf_facts:
            return f"According to the knowledge graph:\n" + "\n".join(f"• {fact}" for fact in high_conf_facts[:3])
        else:
            return "The knowledge graph contains limited information about this topic, but here's what I can provide based on general knowledge..."
    
    async def _update_knowledge_from_interaction(
        self,
        user_query: str,
        agent_response: str,
        knowledge_context: List[Dict[str, Any]]
    ):
        """Update knowledge graph based on this interaction"""
        
        # Extract new knowledge from the interaction
        # In production, this would use NLP to identify new facts
        
        # For demo, log the interaction as potential knowledge
        interaction_summary = {
            "query": user_query,
            "entities_mentioned": [kg.get('question', '') for kg in knowledge_context],
            "confidence_scores": [kg.get('confidence', 0) for kg in knowledge_context],
            "timestamp": datetime.now().isoformat()
        }
        
        print(f"📚 Knowledge interaction logged: {interaction_summary}")
    
    def _calculate_overall_confidence(self, knowledge_context: List[Dict[str, Any]]) -> float:
        """Calculate overall confidence in the response"""
        if not knowledge_context:
            return 0.5  # Medium confidence for general knowledge
        
        confidences = [kg.get('confidence', 0) for kg in knowledge_context]
        return sum(confidences) / len(confidences)

# Example usage
async def demo_knowledge_enhanced_agent():
    """Demonstrate knowledge-enhanced agent capabilities"""
    
    # Initialize knowledge graph
    kg = AgentKnowledgeGraph("bolt://localhost:7687", "neo4j", "password")
    await kg.create_agent_knowledge_schema()
    
    # Add sample knowledge
    await kg.add_knowledge_entity(
        "python_programming",
        "Concept",
        {
            "name": "Python Programming",
            "description": "High-level programming language",
            "domain": "technology",
            "importance": 0.9
        },
        "knowledge_agent"
    )
    
    await kg.add_knowledge_entity(
        "machine_learning",
        "Concept",
        {
            "name": "Machine Learning",
            "description": "AI technique for pattern recognition",
            "domain": "technology",
            "importance": 0.95
        },
        "knowledge_agent"
    )
    
    await kg.add_relationship(
        "python_programming",
        "machine_learning",
        "ENABLES",
        {"strength": 0.8, "confidence": 0.9},
        "knowledge_agent"
    )
    
    # Create knowledge interface
    kg_interface = AgentKnowledgeInterface(kg, "demo_agent")
    
    # Create enhanced agent
    enhanced_agent = KnowledgeEnhancedAgent("Knowledge Assistant", kg_interface)
    
    # Process query
    response = await enhanced_agent.process_query_with_knowledge(
        "How does Python relate to machine learning?"
    )
    
    print(json.dumps(response, indent=2))
    
    kg.close()

# Run the demo
if __name__ == "__main__":
    asyncio.run(demo_knowledge_enhanced_agent())
```

### Graph Query Language Layer: GQL Standard Implementation

The new GQL (Graph Query Language) standard provides a unified approach to querying graph databases.

#### GQL Pattern Implementation

**Future-Ready GQL Query Patterns:**
```python
class GQLQueryBuilder:
    """Builder for GQL standard queries"""
    
    def __init__(self):
        self.schema_definitions = {}
        self.query_templates = {}
        
    def define_agent_schema(self) -> str:
        """Define agent knowledge schema using GQL"""
        
        return """
        CREATE GRAPH TYPE AgentKnowledgeSchema (
            -- Node types for agent knowledge
            Entity (
                id STRING NOT NULL,
                name STRING,
                type STRING,
                description STRING,
                domain STRING,
                importance FLOAT DEFAULT 0.5,
                created_at TIMESTAMP,
                created_by_agent STRING
            ),
            
            Concept EXTENDS Entity (
                definition STRING,
                examples STRING[]
            ),
            
            Person EXTENDS Entity (
                email STRING,
                expertise STRING[]
            ),
            
            Event EXTENDS Entity (
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                location STRING
            ),
            
            -- Edge types for relationships
            RELATES_TO (
                type STRING NOT NULL,
                confidence FLOAT DEFAULT 1.0,
                strength FLOAT DEFAULT 0.5,
                created_at TIMESTAMP,
                created_by_agent STRING
            ),
            
            CAUSES EXTENDS RELATES_TO (
                causality_strength FLOAT,
                time_delay STRING
            ),
            
            SIMILAR_TO EXTENDS RELATES_TO (
                similarity_score FLOAT
            )
        );
        
        -- Create instance of the schema
        CREATE GRAPH AgentKnowledge OF TYPE AgentKnowledgeSchema;
        """
    
    def build_entity_query(
        self,
        entity_type: str = None,
        properties: Dict[str, Any] = None,
        limit: int = 50
    ) -> str:
        """Build GQL query for finding entities"""
        
        # Base pattern
        pattern = "MATCH (e:Entity)"
        
        # Add type filter
        if entity_type:
            pattern = f"MATCH (e:{entity_type})"
        
        # Add property filters
        where_clauses = []
        if properties:
            for prop, value in properties.items():
                if isinstance(value, str):
                    where_clauses.append(f"e.{prop} = '{value}'")
                else:
                    where_clauses.append(f"e.{prop} = {value}")
        
        where_clause = ""
        if where_clauses:
            where_clause = "WHERE " + " AND ".join(where_clauses)
        
        return f"""
        {pattern}
        {where_clause}
        RETURN e.id, e.name, e.type, e.description, e.importance
        ORDER BY e.importance DESC
        LIMIT {limit}
        """
    
    def build_relationship_traversal(
        self,
        start_entity: str,
        relationship_types: List[str] = None,
        max_depth: int = 3
    ) -> str:
        """Build GQL query for relationship traversal"""
        
        # Relationship filter
        rel_filter = "RELATES_TO"
        if relationship_types:
            rel_types = "|".join(relationship_types)
            rel_filter = f"({rel_types})"
        
        return f"""
        MATCH (start:Entity {{id: '{start_entity}'}})
        MATCH (start)-[r:{rel_filter}*1..{max_depth}]-(connected:Entity)
        
        RETURN DISTINCT 
            connected.id as entity_id,
            connected.name as name,
            connected.type as type,
            length(r) as distance,
            [rel in r | rel.type] as relationship_path,
            reduce(conf = 1.0, rel in r | conf * rel.confidence) as path_confidence
        
        ORDER BY distance, path_confidence DESC
        LIMIT 100
        """
    
    def build_pattern_detection(
        self,
        pattern_type: str = "triangular"
    ) -> str:
        """Build GQL query for pattern detection"""
        
        if pattern_type == "triangular":
            return """
            MATCH (a:Entity)-[r1:RELATES_TO]->(b:Entity)-[r2:RELATES_TO]->(c:Entity)-[r3:RELATES_TO]->(a)
            WHERE a.id < b.id AND b.id < c.id  -- Avoid duplicate triangles
            
            RETURN a.name as entity_a,
                   b.name as entity_b, 
                   c.name as entity_c,
                   r1.type as rel_ab,
                   r2.type as rel_bc,
                   r3.type as rel_ca,
                   (r1.confidence * r2.confidence * r3.confidence) as triangle_strength
            
            ORDER BY triangle_strength DESC
            LIMIT 20
            """
        elif pattern_type == "star":
            return """
            MATCH (center:Entity)
            MATCH (center)-[r:RELATES_TO]-(connected:Entity)
            
            WITH center, count(connected) as connection_count, collect(connected) as neighbors
            WHERE connection_count >= 5
            
            RETURN center.name as center_entity,
                   center.type as center_type,
                   connection_count,
                   [neighbor in neighbors | neighbor.name][0..10] as sample_neighbors
            
            ORDER BY connection_count DESC
            LIMIT 10
            """
        else:
            return f"-- Pattern type '{pattern_type}' not implemented"
    
    def build_reasoning_query(
        self,
        premise_entity: str,
        conclusion_entity: str,
        reasoning_type: str = "causal"
    ) -> str:
        """Build GQL query for reasoning chains"""
        
        if reasoning_type == "causal":
            rel_types = "CAUSES|LEADS_TO|INFLUENCES"
        elif reasoning_type == "categorical":
            rel_types = "IS_A|INSTANCE_OF|SUBCLASS_OF"
        elif reasoning_type == "associative":
            rel_types = "SIMILAR_TO|RELATED_TO|ASSOCIATED_WITH"
        else:
            rel_types = "RELATES_TO"
        
        return f"""
        MATCH (premise:Entity {{name: '{premise_entity}'}})
        MATCH (conclusion:Entity {{name: '{conclusion_entity}'}})
        
        MATCH path = (premise)-[r:({rel_types})*1..4]-(conclusion)
        
        RETURN 
            [node in nodes(path) | {{
                name: node.name,
                type: node.type,
                importance: node.importance
            }}] as reasoning_chain,
            
            [rel in relationships(path) | {{
                type: rel.type,
                confidence: rel.confidence,
                strength: rel.strength
            }}] as reasoning_steps,
            
            length(path) as reasoning_length,
            reduce(conf = 1.0, rel in relationships(path) | conf * rel.confidence) as reasoning_confidence
        
        ORDER BY reasoning_confidence DESC, reasoning_length ASC
        LIMIT 5
        """

# GQL Schema Evolution Support
class GQLSchemaManager:
    """Manage GQL schema evolution for agent knowledge"""
    
    def __init__(self, database_connection):
        self.db = database_connection
        self.schema_versions = {}
        
    async def evolve_schema_for_new_domain(
        self,
        domain_name: str,
        new_entity_types: List[Dict[str, Any]],
        new_relationship_types: List[Dict[str, Any]]
    ) -> bool:
        """Evolve schema to support new knowledge domains"""
        
        schema_updates = []
        
        # Add new entity types
        for entity_type in new_entity_types:
            type_name = entity_type["name"]
            properties = entity_type["properties"]
            
            prop_definitions = []
            for prop_name, prop_config in properties.items():
                prop_type = prop_config["type"]
                required = "NOT NULL" if prop_config.get("required") else ""
                default = f"DEFAULT {prop_config['default']}" if "default" in prop_config else ""
                
                prop_definitions.append(f"{prop_name} {prop_type} {required} {default}".strip())
            
            schema_update = f"""
            ALTER GRAPH TYPE AgentKnowledgeSchema 
            ADD NODE TYPE {type_name} EXTENDS Entity (
                {', '.join(prop_definitions)}
            );
            """
            
            schema_updates.append(schema_update)
        
        # Add new relationship types
        for rel_type in new_relationship_types:
            type_name = rel_type["name"]
            properties = rel_type.get("properties", {})
            
            prop_definitions = []
            for prop_name, prop_config in properties.items():
                prop_type = prop_config["type"]
                required = "NOT NULL" if prop_config.get("required") else ""
                
                prop_definitions.append(f"{prop_name} {prop_type} {required}".strip())
            
            schema_update = f"""
            ALTER GRAPH TYPE AgentKnowledgeSchema
            ADD EDGE TYPE {type_name} EXTENDS RELATES_TO (
                {', '.join(prop_definitions)}
            );
            """
            
            schema_updates.append(schema_update)
        
        # Execute schema updates
        try:
            for update in schema_updates:
                await self.db.execute(update)
            
            print(f"✅ Schema evolved for domain: {domain_name}")
            self.schema_versions[domain_name] = {
                "updated_at": datetime.now().isoformat(),
                "entity_types": [et["name"] for et in new_entity_types],
                "relationship_types": [rt["name"] for rt in new_relationship_types]
            }
            
            return True
            
        except Exception as e:
            print(f"❌ Schema evolution failed: {e}")
            return False
```

---

## Mental Model: Thinking in Relationships and Reasoning

### Build the Mental Model: From Information to Knowledge

Think of the progression from data to knowledge like **building a city**:

**Raw Data**: Scattered building materials
- **Unstructured**: Information without context
- **Isolated**: No connections between pieces
- **Limited utility**: Hard to find and use

**Knowledge Graph**: Planned city with infrastructure
- **Structured**: Information organized by relationships
- **Connected**: Clear paths between related concepts
- **High utility**: Easy to navigate and discover new insights

### Why It's Designed This Way: Enabling Machine Reasoning

Knowledge graphs enable sophisticated agent reasoning by:

1. **Explicit Relationships**: Agents can follow logical connections
2. **Multi-hop Reasoning**: Discovering insights through relationship chains
3. **Contextual Understanding**: Rich context through graph neighborhoods
4. **Confidence Tracking**: Uncertainty quantification in reasoning paths

### Further Exploration: Advanced Graph Reasoning

**Immediate Practice:**
1. Set up Neo4j with agent knowledge schema
2. Implement natural language to graph query translation
3. Build reasoning chains using graph traversal
4. Create agent memory using persistent graph storage

**Design Challenge:**
Create a "knowledge-driven research assistant" that:
- Builds knowledge graphs from research papers
- Reasons across multiple domains using graph relationships
- Explains its reasoning using graph visualization
- Continuously updates knowledge from new sources

**Advanced Exploration:**
- How would you implement temporal reasoning in knowledge graphs?
- What patterns support collaborative knowledge building between agents?
- How could you create knowledge graph embeddings for semantic search?
- What techniques enable privacy-preserving knowledge sharing?

---

*Knowledge graphs and graph query languages transform AI agents from pattern-matching systems into reasoning systems capable of understanding, inferring, and explaining complex relationships. These structured knowledge foundations enable agents to perform sophisticated reasoning, provide explainable decisions, and continuously expand their understanding through relationship discovery and logical inference.*