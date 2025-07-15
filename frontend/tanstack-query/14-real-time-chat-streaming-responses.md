# Real-Time Chat: Streaming Responses

> **Based on**: [`examples/react/chat`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/chat)

## The Core Concept: Why This Example Exists

**The Problem:** Modern chat applications need to handle streaming responses where content arrives progressively, word by word or chunk by chunk. Traditional data fetching waits for complete responses before updating the UI, creating poor user experiences in chat scenarios where users expect to see responses appearing in real-time, similar to ChatGPT or other AI assistants.

**The Solution:** TanStack Query's **experimental streaming support** enables **progressive data updates** where partial responses update the UI as data arrives. This creates chat experiences that feel alive and responsive, with content appearing gradually rather than all at once.

The key insight: **streaming transforms queries from discrete snapshots into living, updateable data flows**. Instead of waiting for complete responses, the UI updates incrementally as each piece of data arrives, creating engaging real-time experiences.

## Practical Walkthrough: Code Breakdown

Let's examine the streaming chat patterns from `examples/react/chat/`:

### 1. Streaming Query Function

```tsx
// chat.ts
function chatAnswer(_question: string) {
  return {
    async *[Symbol.asyncIterator]() {
      const answer = answers[Math.floor(Math.random() * answers.length)]
      let index = 0
      while (index < answer.length) {
        await new Promise((resolve) =>
          setTimeout(resolve, 100 + Math.random() * 300),
        )
        yield answer[index++]
      }
    },
  }
}
```

**What's happening:** The function returns an async iterator that yields individual words with random delays, simulating a streaming response from a chat service.

**Why async iterators:** This is JavaScript's native streaming interface. Each `yield` provides a new piece of data, and the `await` creates realistic delays between words.

### 2. Streamed Query Configuration

```tsx
export const chatQueryOptions = (question: string) =>
  queryOptions({
    queryKey: ['chat', question],
    queryFn: streamedQuery({
      queryFn: () => chatAnswer(question),
    }),
    staleTime: Infinity,
  })
```

**What's happening:** `streamedQuery` wraps the async iterator function, enabling TanStack Query to handle streaming updates. `staleTime: Infinity` prevents re-fetching of completed chat responses.

**Why streamedQuery wrapper:** TanStack Query needs special handling for streaming data. The wrapper coordinates between the async iterator and Query's caching system.

### 3. Progressive UI Updates

```tsx
function ChatMessage({ question }: { question: string }) {
  const { error, data = [], isFetching } = useQuery(chatQueryOptions(question))

  if (error) return 'An error has occurred: ' + error.message

  return (
    <div>
      <Message message={{ content: question, isQuestion: true }} />
      <Message
        inProgress={isFetching}
        message={{ content: data.join(' '), isQuestion: false }}
      />
    </div>
  )
}
```

**What's happening:** The `data` array accumulates words as they stream in. The UI shows the joined content, updating with each new word. The `inProgress` prop indicates when streaming is active.

**Why join the array:** Each stream update adds a new word to the data array. Joining creates the full message text while preserving the progressive nature of the updates.

### 4. Chat Message Interface

```tsx
export function Message({
  inProgress,
  message,
}: {
  inProgress?: boolean
  message: { content: string; isQuestion: boolean }
}) {
  return (
    <div className={`flex ${message.isQuestion ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] rounded-lg p-3 ${
        message.isQuestion
          ? 'bg-blue-500 text-white'
          : 'bg-gray-200 text-gray-800'
      }`}>
        {message.content}
        {inProgress ? '...' : null}
      </div>
    </div>
  )
}
```

**What's happening:** Messages are styled differently for questions (right-aligned, blue) vs answers (left-aligned, gray). The ellipsis indicates when a response is still streaming.

**Why visual distinction:** Chat interfaces need clear visual hierarchy. Different styling for different message types helps users follow conversations easily.

### 5. Chat State Management

```tsx
function Example() {
  const [questions, setQuestions] = useState<Array<string>>([])
  const [currentQuestion, setCurrentQuestion] = useState('')

  const submitMessage = () => {
    setQuestions([...questions, currentQuestion])
    setCurrentQuestion('')
  }

  return (
    <div className="flex flex-col h-screen max-w-3xl mx-auto p-4">
      <div className="overflow-y-auto mb-4 space-y-4">
        {questions.map((question) => (
          <ChatMessage key={question} question={question} />
        ))}
      </div>
      {/* Input form */}
    </div>
  )
}
```

**What's happening:** Simple state management tracks submitted questions. Each question triggers a new ChatMessage component that handles its own streaming response.

**Why question-based keys:** Each question gets its own cache entry and streaming response. Using the question as a key ensures proper React reconciliation.

## Mental Model: Streaming as Incremental Queries

### The Streaming Data Flow

```
Traditional Query:
Request → Wait → Complete Response → Update UI

Streaming Query:
Request → Partial Response 1 → Update UI
       → Partial Response 2 → Update UI
       → Partial Response 3 → Update UI
       → Complete → Final UI
```

Each partial response triggers a re-render with accumulated data.

### Cache Behavior with Streaming

```
Query Cache Entry:
['chat', 'Hello'] → {
  data: ['Hello', 'there!', 'How', 'can', 'I', 'help?'],
  status: 'success',
  isFetching: false
}

UI Display:
"Hello there! How can I help?"
```

The cache accumulates all streamed chunks, providing the complete response for future access.

### Progressive State Updates

```
Stream Progress:
Time 0: data = [] → UI shows ""
Time 1: data = ["Hello"] → UI shows "Hello"
Time 2: data = ["Hello", "there!"] → UI shows "Hello there!"
Time 3: data = ["Hello", "there!", "How"] → UI shows "Hello there! How"
Final: data = ["Hello", "there!", "How", "can", "I", "help?"] → UI shows complete message
```

### Why It's Designed This Way: Engaging User Experience

Static responses feel disconnected:
```
User sends message → Loading... → Complete response appears
```

Streaming responses feel conversational:
```
User sends message → Response begins appearing → Words stream in → Natural conversation flow
```

This mimics human conversation patterns and maintains user engagement.

### Advanced Streaming Patterns

**Real Chat Service Integration**: Connect to actual streaming APIs:
```tsx
function chatWithService(question: string) {
  return {
    async *[Symbol.asyncIterator]() {
      const response = await fetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({ question }),
        headers: { 'Content-Type': 'application/json' }
      })
      
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      
      while (true) {
        const { done, value } = await reader!.read()
        if (done) break
        
        const chunk = decoder.decode(value)
        const words = chunk.split(' ')
        
        for (const word of words) {
          if (word.trim()) {
            yield word
          }
        }
      }
    },
  }
}
```

**Typed Streaming Responses**: Strong typing for streaming data:
```tsx
interface StreamingChatResponse {
  type: 'word' | 'metadata' | 'complete'
  content: string
  metadata?: {
    timestamp: number
    confidence: number
  }
}

function typedChatStream(question: string) {
  return {
    async *[Symbol.asyncIterator](): AsyncIterator<StreamingChatResponse> {
      // Yield typed streaming responses
      yield { type: 'word', content: 'Hello' }
      yield { type: 'word', content: 'there!' }
      yield { type: 'complete', content: '' }
    },
  }
}
```

**Multi-Modal Streaming**: Handle different content types:
```tsx
interface MultiModalChunk {
  type: 'text' | 'image' | 'code' | 'link'
  content: string
  metadata?: Record<string, any>
}

function multiModalStream(question: string) {
  return {
    async *[Symbol.asyncIterator](): AsyncIterator<MultiModalChunk> {
      yield { type: 'text', content: 'Here is the code:' }
      yield { type: 'code', content: 'console.log("hello")', metadata: { language: 'javascript' } }
      yield { type: 'text', content: 'And here is a helpful link:' }
      yield { type: 'link', content: 'https://example.com', metadata: { title: 'Documentation' } }
    },
  }
}
```

**Streaming with Error Handling**: Graceful error recovery:
```tsx
function robustChatStream(question: string) {
  return {
    async *[Symbol.asyncIterator]() {
      try {
        for await (const chunk of chatService.stream(question)) {
          yield chunk
        }
      } catch (error) {
        yield `Sorry, I encountered an error: ${error.message}`
        throw error // Let TanStack Query handle the error state
      }
    },
  }
}

// In component
const { data = [], error, isFetching } = useQuery({
  queryKey: ['chat', question],
  queryFn: streamedQuery({
    queryFn: () => robustChatStream(question),
  }),
  retry: (failureCount, error) => {
    // Custom retry logic for streaming failures
    return failureCount < 2 && !error.message.includes('quota')
  }
})
```

**Conversation History**: Maintain chat context:
```tsx
interface ChatContext {
  messages: Array<{ role: 'user' | 'assistant', content: string }>
}

function contextualChatStream(question: string, context: ChatContext) {
  return {
    async *[Symbol.asyncIterator]() {
      const fullContext = {
        ...context,
        messages: [...context.messages, { role: 'user', content: question }]
      }
      
      // Send full context to maintain conversation coherence
      for await (const chunk of chatService.streamWithContext(fullContext)) {
        yield chunk
      }
    },
  }
}
```

### Performance Considerations

**Streaming Frequency**: Balance responsiveness vs performance:
```tsx
// Debounce rapid updates to prevent excessive re-renders
const debouncedStreamedQuery = (queryFn) => 
  streamedQuery({
    queryFn,
    throttleMs: 50 // Only update UI every 50ms max
  })
```

**Memory Management**: Handle long conversations:
```tsx
// Implement sliding window for long chat histories
const useChatWithWindow = (maxMessages = 50) => {
  const [questions, setQuestions] = useState<string[]>([])
  
  const addQuestion = (question: string) => {
    setQuestions(prev => {
      const updated = [...prev, question]
      return updated.length > maxMessages 
        ? updated.slice(-maxMessages)
        : updated
    })
  }
  
  return { questions, addQuestion }
}
```

**Cleanup and Cancellation**: Proper resource management:
```tsx
// Streaming queries automatically cancel when component unmounts
useEffect(() => {
  return () => {
    // Cleanup any additional resources
    chatService.closeConnections()
  }
}, [])
```

### Further Exploration

Experiment with streaming patterns:

1. **Response Timing**: Try different streaming speeds and chunk sizes
2. **Error Scenarios**: Test network interruptions during streaming
3. **Real APIs**: Integrate with actual streaming chat services
4. **Multi-turn Conversations**: Maintain context across multiple messages

**Advanced Challenges**:

1. **Collaborative Chat**: How would you implement multi-user chat with streaming responses?

2. **Voice Integration**: How would you combine streaming text with text-to-speech for voice responses?

3. **Rich Content**: How would you stream and render complex content like tables, charts, or interactive elements?

4. **Conversation Branching**: How would you implement conversation trees where users can explore different response paths?

**Real-World Applications**:
- **AI Assistants**: ChatGPT-style interfaces with streaming responses
- **Customer Support**: Live chat with agent typing indicators
- **Code Generation**: IDEs with streaming code completion and explanation
- **Documentation**: Interactive help systems with progressive responses
- **Educational Platforms**: Tutoring systems with step-by-step explanations

Streaming responses transform static question-answer interactions into dynamic, engaging conversations. Understanding these patterns enables building modern chat interfaces that feel natural, responsive, and alive - creating user experiences that rival the best AI assistants and chat applications.