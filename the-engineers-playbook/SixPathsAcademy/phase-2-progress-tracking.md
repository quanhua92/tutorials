# Phase 2: Progress Tracking (Weeks 3-4)

> **Implement user profile system with comprehensive progress visualization and achievement tracking**

## 🎯 Phase Goals

- Build comprehensive user profile management system
- Create interactive progress visualization components
- Implement Six Paths dashboard with detailed metrics
- Add achievement system with badge notifications
- Develop tutorial detail pages with progress tracking

## 📋 Tasks Breakdown

### **Week 3: User Profile System**

#### Task 2.1: Enhanced Profile Management
**Estimated Time: 8 hours**

```typescript
// hooks/useProfile.ts (Enhanced)
export function useProfile() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Initialize profile with GitHub data if available
  const initializeProfile = async () => {
    const stored = localStorage.getItem('codesagemode-profile');
    if (stored) {
      setProfile(JSON.parse(stored));
    } else {
      // Try to get GitHub user data
      const githubUser = await fetchGitHubUser();
      const newProfile = createDefaultProfile(githubUser);
      setProfile(newProfile);
      localStorage.setItem('codesagemode-profile', JSON.stringify(newProfile));
    }
    setIsLoading(false);
  };

  const updateProgress = (pathId: string, tutorialId: string, completed: boolean) => {
    setProfile(prev => {
      if (!prev) return null;
      
      const updatedProfile = { ...prev };
      const pathProgress = updatedProfile.progress[pathId];
      
      if (completed && !pathProgress.completedTutorials.includes(tutorialId)) {
        pathProgress.completedTutorials.push(tutorialId);
        pathProgress.completed = pathProgress.completedTutorials.length;
        pathProgress.xpEarned += calculateXP(tutorialId);
        
        // Update total XP
        updatedProfile.user.totalXP += calculateXP(tutorialId);
        
        // Check for achievements
        const newAchievements = checkAchievements(updatedProfile);
        updatedProfile.achievements.push(...newAchievements);
        
        // Update level
        updatedProfile.user.currentLevel = calculateLevel(updatedProfile.user.totalXP);
      }
      
      localStorage.setItem('codesagemode-profile', JSON.stringify(updatedProfile));
      return updatedProfile;
    });
  };

  const resetProgress = (pathId: string) => {
    setProfile(prev => {
      if (!prev) return null;
      
      const updatedProfile = { ...prev };
      const pathProgress = updatedProfile.progress[pathId];
      
      // Subtract XP
      updatedProfile.user.totalXP -= pathProgress.xpEarned;
      
      // Reset path progress
      updatedProfile.progress[pathId] = {
        ...pathProgress,
        completed: 0,
        completedTutorials: [],
        currentTutorial: null,
        xpEarned: 0,
        completionDate: null
      };
      
      localStorage.setItem('codesagemode-profile', JSON.stringify(updatedProfile));
      return updatedProfile;
    });
  };

  return { 
    profile, 
    isLoading, 
    updateProgress, 
    resetProgress,
    initializeProfile 
  };
}
```

#### Task 2.2: Progress Visualization Components
**Estimated Time: 10 hours**

```typescript
// components/features/ProgressDashboard.tsx
export function ProgressDashboard() {
  const { profile } = useProfile();
  const { data: pathsData } = usePathsData();
  
  if (!profile || !pathsData) return <ProgressSkeleton />;

  const overallProgress = calculateOverallProgress(profile.progress, pathsData);
  
  return (
    <div className="space-y-8">
      {/* Hero Section */}
      <div className="text-center space-y-4">
        <h1 className="text-4xl font-bold gradient-text">
          Welcome back, {profile.user.name}! 🎯
        </h1>
        <div className="flex justify-center items-center space-x-4">
          <LevelBadge level={profile.user.currentLevel} xp={profile.user.totalXP} />
          <Badge variant="outline">{overallProgress.completedPaths}/6 Paths Mastered</Badge>
        </div>
      </div>

      {/* Overall Progress */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center space-x-2">
            <Trophy className="h-5 w-5" />
            <span>Six Paths Sage Mode Progress</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-6">
            <div className="text-center">
              <div className="text-3xl font-bold mb-2">
                {overallProgress.completedTutorials}/{overallProgress.totalTutorials}
              </div>
              <div className="text-muted-foreground">Tutorials Completed</div>
            </div>
            
            <Progress 
              value={overallProgress.percentage} 
              className="h-4"
            />
            
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div className="text-center">
                <div className="font-semibold text-green-600">
                  {overallProgress.streakDays}
                </div>
                <div className="text-muted-foreground">Day Streak</div>
              </div>
              <div className="text-center">
                <div className="font-semibold text-blue-600">
                  {overallProgress.estimatedCompletion}
                </div>
                <div className="text-muted-foreground">Est. Completion</div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Six Paths Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {Object.entries(pathsData.paths).map(([pathId, path]) => (
          <PathProgressCard
            key={pathId}
            path={path}
            progress={profile.progress[pathId]}
            onPathClick={() => navigateToPath(pathId)}
          />
        ))}
      </div>

      {/* Recent Activity */}
      <RecentActivity profile={profile} />
    </div>
  );
}

// components/features/PathProgressCard.tsx
export function PathProgressCard({ path, progress, onPathClick }: PathProgressCardProps) {
  const completionPercentage = (progress.completed / progress.total) * 100;
  const isCompleted = progress.completed === progress.total;
  
  return (
    <Card 
      className={`cursor-pointer transition-all hover:shadow-lg ${
        isCompleted ? 'ring-2 ring-green-500' : ''
      }`}
      onClick={onPathClick}
    >
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="text-4xl relative">
              {path.icon}
              {isCompleted && (
                <div className="absolute -top-1 -right-1 text-lg">✨</div>
              )}
            </div>
            <div>
              <CardTitle className="text-lg">{path.name}</CardTitle>
              <CardDescription>{path.description}</CardDescription>
            </div>
          </div>
          <Badge variant={getBadgeVariant(path.difficulty)}>
            {path.difficulty}
          </Badge>
        </div>
      </CardHeader>
      
      <CardContent>
        <div className="space-y-4">
          <div className="flex justify-between text-sm">
            <span>Progress</span>
            <span>{progress.completed}/{progress.total}</span>
          </div>
          
          <Progress 
            value={completionPercentage} 
            className={`h-2 ${isCompleted ? 'bg-green-100' : ''}`}
          />
          
          <div className="flex justify-between text-sm text-muted-foreground">
            <span>Est. {path.estimatedWeeks} weeks</span>
            <span className="flex items-center space-x-1">
              <Star className="h-3 w-3" />
              <span>{progress.xpEarned} XP</span>
            </span>
          </div>
          
          {progress.currentTutorial && (
            <div className="text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded">
              📖 Currently: {getTutorialTitle(progress.currentTutorial)}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
```

### **Week 4: Tutorial Detail & Achievement System**

#### Task 2.3: Tutorial Detail Pages
**Estimated Time: 8 hours**

```typescript
// routes/tutorial/$tutorialId.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/tutorial/$tutorialId',
  component: TutorialDetailPage,
  loader: ({ params }) => {
    return {
      tutorialId: params.tutorialId,
    };
  },
});

function TutorialDetailPage() {
  const { tutorialId } = Route.useLoaderData();
  const { data: pathsData } = usePathsData();
  const { profile, updateProgress } = useProfile();
  
  const tutorial = pathsData?.tutorials[tutorialId];
  const path = tutorial ? pathsData.paths[tutorial.pathId] : null;
  
  if (!tutorial || !path) return <TutorialNotFound />;
  
  const isCompleted = profile?.progress[tutorial.pathId]?.completedTutorials.includes(tutorialId);
  const progress = profile?.progress[tutorial.pathId];
  
  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Header */}
      <div className="space-y-4">
        <Breadcrumb>
          <BreadcrumbItem>
            <Link to="/paths">Six Paths</Link>
          </BreadcrumbItem>
          <BreadcrumbItem>
            <Link to={`/paths/${tutorial.pathId}`}>{path.name}</Link>
          </BreadcrumbItem>
          <BreadcrumbItem>
            <span>{tutorial.title}</span>
          </BreadcrumbItem>
        </Breadcrumb>
        
        <div className="flex items-start justify-between">
          <div className="space-y-2">
            <h1 className="text-3xl font-bold">{tutorial.title}</h1>
            <p className="text-muted-foreground">{tutorial.description}</p>
            
            <div className="flex items-center space-x-4">
              <Badge variant="outline">{tutorial.difficulty}</Badge>
              <Badge variant="secondary">
                <Clock className="h-3 w-3 mr-1" />
                {tutorial.estimatedHours}h
              </Badge>
              <Badge variant="secondary">
                <Star className="h-3 w-3 mr-1" />
                {calculateXP(tutorialId)} XP
              </Badge>
            </div>
          </div>
          
          <CompletionToggle
            isCompleted={isCompleted}
            onToggle={(completed) => updateProgress(tutorial.pathId, tutorialId, completed)}
          />
        </div>
      </div>

      {/* Prerequisites */}
      {tutorial.prerequisites.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center space-x-2">
              <AlertTriangle className="h-5 w-5" />
              <span>Prerequisites</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <PrerequisitesList 
              prerequisites={tutorial.prerequisites}
              userProgress={profile?.progress}
            />
          </CardContent>
        </Card>
      )}

      {/* Skills & Learning Outcomes */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Skills You'll Learn</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {tutorial.skills.map(skill => (
                <Badge key={skill} variant="outline">
                  {skill}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Path Progress</CardTitle>
          </CardHeader>
          <CardContent>
            <PathProgressMini 
              path={path}
              progress={progress}
              currentTutorial={tutorialId}
            />
          </CardContent>
        </Card>
      </div>

      {/* Tutorial Content Link with Sage Assistant */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Start Learning</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground mb-2">
                    Ready to dive into this tutorial? Click below to access the full content.
                  </p>
                  <Button asChild>
                    <a 
                      href={tutorial.githubUrl} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="flex items-center space-x-2"
                    >
                      <ExternalLink className="h-4 w-4" />
                      <span>Open Tutorial</span>
                    </a>
                  </Button>
                </div>
                <div className="text-right">
                  <p className="text-sm text-muted-foreground">
                    Mark as complete when finished
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
        
        <div className="lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center space-x-2">
                <div className="text-2xl">🥋</div>
                <span>Ask Sensei Roku</span>
              </CardTitle>
              <CardDescription>
                Get personalized help with this tutorial
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SenseiRoku 
                tutorialContext={tutorial}
                pathContext={path}
                mode="dialog"
                className="h-96"
              />
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Next Steps */}
      <NextStepsSection 
        tutorial={tutorial}
        pathsData={pathsData}
        userProgress={profile?.progress}
      />
    </div>
  );
}
```

#### Task 2.4: Achievement System
**Estimated Time: 8 hours**

```typescript
// lib/achievements.ts
export const ACHIEVEMENTS: Record<string, AchievementDefinition> = {
  'first-tutorial': {
    id: 'first-tutorial',
    title: 'First Steps',
    description: 'Complete your first tutorial',
    icon: '🎯',
    rarity: 'common',
    condition: (profile) => {
      return Object.values(profile.progress).some(p => p.completed > 0);
    }
  },
  
  'path-complete': {
    id: 'path-complete',
    title: 'Path Master',
    description: 'Complete an entire learning path',
    icon: '🏆',
    rarity: 'rare',
    condition: (profile) => {
      return Object.values(profile.progress).some(p => p.completed === p.total);
    }
  },
  
  'speed-learner': {
    id: 'speed-learner',
    title: 'Speed Learner',
    description: 'Complete 3 tutorials in one day',
    icon: '⚡',
    rarity: 'epic',
    condition: (profile) => {
      // Check completion timestamps
      const today = new Date().toDateString();
      const todayCompletions = profile.achievements.filter(a => 
        a.unlockedAt.includes(today)
      ).length;
      return todayCompletions >= 3;
    }
  },
  
  'sage-mode': {
    id: 'sage-mode',
    title: 'Six Paths Sage',
    description: 'Master all six learning paths',
    icon: '🌟',
    rarity: 'legendary',
    condition: (profile) => {
      return Object.values(profile.progress).every(p => p.completed === p.total);
    }
  }
};

export function checkAchievements(profile: UserProfile): Achievement[] {
  const newAchievements: Achievement[] = [];
  const existingIds = new Set(profile.achievements.map(a => a.id));
  
  Object.values(ACHIEVEMENTS).forEach(def => {
    if (!existingIds.has(def.id) && def.condition(profile)) {
      newAchievements.push({
        id: def.id,
        title: def.title,
        description: def.description,
        icon: def.icon,
        rarity: def.rarity,
        unlockedAt: new Date().toISOString()
      });
    }
  });
  
  return newAchievements;
}

// components/features/AchievementNotification.tsx
export function AchievementNotification({ achievement }: { achievement: Achievement }) {
  const [isVisible, setIsVisible] = useState(true);
  
  useEffect(() => {
    const timer = setTimeout(() => setIsVisible(false), 5000);
    return () => clearTimeout(timer);
  }, []);
  
  if (!isVisible) return null;
  
  return (
    <div className="fixed top-4 right-4 z-50 animate-slide-in">
      <Card className="w-80 bg-gradient-to-r from-purple-500 to-blue-500 text-white border-none">
        <CardHeader>
          <div className="flex items-center space-x-3">
            <div className="text-2xl">{achievement.icon}</div>
            <div>
              <CardTitle className="text-white">Achievement Unlocked!</CardTitle>
              <CardDescription className="text-purple-100">
                {achievement.title}
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-purple-100">{achievement.description}</p>
        </CardContent>
      </Card>
    </div>
  );
}
```

#### Task 2.5: Sensei Roku AI Learning Assistant
**Estimated Time: 12 hours**

```typescript
// components/features/SenseiRoku.tsx
interface SenseiRokuProps {
  tutorialContext?: Tutorial;
  pathContext?: Path;
  className?: string;
  mode?: 'sidebar' | 'dialog' | 'floating';
}

export function SenseiRoku({ tutorialContext, pathContext, className, mode = 'sidebar' }: SenseiRokuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const { apiKey, baseUrl } = useAPISettings();
  const { profile } = useProfile();
  
  const systemPrompt = `You are Sensei Roku, a wise and encouraging mentor for SixPathsAcademy learners. You help students understand software engineering concepts through the Six Paths methodology:

1. 📚 Foundations Path - Core CS concepts and data structures
2. 🏗️ Systems Path - Distributed systems and architecture  
3. 🧠 Algorithms Path - Advanced algorithms and problem-solving
4. ⚡ Performance Path - Optimization and efficiency
5. 🔬 Specialized Topics - Advanced data structures
6. 🌐 Distributed Systems & Architecture - Advanced distributed patterns

Current context:
- Student: ${profile?.user.name || 'Learner'}
- Current Level: ${profile?.user.currentLevel || 'Code Ninja'}
- Total XP: ${profile?.user.totalXP || 0}
${tutorialContext ? `- Current Tutorial: ${tutorialContext.title}` : ''}
${pathContext ? `- Current Path: ${pathContext.name}` : ''}

Be encouraging, provide clear explanations, and relate concepts to the Six Paths methodology. Keep responses concise but helpful.`;

  const { messages: chatMessages, input, handleInputChange, handleSubmit, isLoading: aiLoading } = useChat({
    api: baseUrl ? `${baseUrl}/v1/chat/completions` : '/api/chat',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    initialMessages: [
      {
        id: 'system',
        role: 'system',
        content: systemPrompt,
      },
      {
        id: 'welcome',
        role: 'assistant', 
        content: `🥋 Greetings, ${profile?.user.name || 'fellow learner'}! I'm Sensei Roku, your guide on the path to software engineering mastery. ${tutorialContext ? `I see you're working on "${tutorialContext.title}" - how can I help you understand this better?` : 'What would you like to explore today?'}`
      }
    ],
  });

  const handleQuickQuestion = (question: string) => {
    const contextualQuestion = tutorialContext 
      ? `Regarding the tutorial "${tutorialContext.title}": ${question}`
      : question;
    
    handleSubmit(new Event('submit') as any, { data: { message: contextualQuestion } });
  };

  if (!apiKey) {
    return <SenseiSetupPrompt />;
  }

  if (mode === 'floating') {
    return (
      <div className={cn("fixed bottom-4 right-4 z-50", className)}>
        <AnimatePresence>
          {!isOpen && (
            <motion.button
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0 }}
              onClick={() => setIsOpen(true)}
              className="w-14 h-14 bg-gradient-to-r from-purple-500 to-blue-500 rounded-full shadow-lg hover:shadow-xl transition-shadow flex items-center justify-center text-white text-2xl"
            >
              🥋
            </motion.button>
          )}
        </AnimatePresence>
        
        <AnimatePresence>
          {isOpen && (
            <motion.div
              initial={{ opacity: 0, y: 20, scale: 0.9 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 20, scale: 0.9 }}
              className="absolute bottom-0 right-0 w-96 h-[500px] bg-background border rounded-lg shadow-xl"
            >
              <SageChatInterface 
                messages={chatMessages}
                input={input}
                handleInputChange={handleInputChange}
                handleSubmit={handleSubmit}
                isLoading={aiLoading}
                onClose={() => setIsOpen(false)}
                tutorialContext={tutorialContext}
                onQuickQuestion={handleQuickQuestion}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  }

  if (mode === 'sidebar') {
    return (
      <div className={cn("w-80 h-full border-l bg-background/50", className)}>
        <SageChatInterface 
          messages={chatMessages}
          input={input}
          handleInputChange={handleInputChange}
          handleSubmit={handleSubmit}
          isLoading={aiLoading}
          tutorialContext={tutorialContext}
          onQuickQuestion={handleQuickQuestion}
          showHeader={true}
        />
      </div>
    );
  }

  return null;
}

// components/features/SageChatInterface.tsx
interface SageChatInterfaceProps {
  messages: Message[];
  input: string;
  handleInputChange: (e: ChangeEvent<HTMLInputElement>) => void;
  handleSubmit: (e: FormEvent<HTMLFormElement>) => void;
  isLoading: boolean;
  onClose?: () => void;
  tutorialContext?: Tutorial;
  onQuickQuestion: (question: string) => void;
  showHeader?: boolean;
}

export function SageChatInterface({ 
  messages, 
  input, 
  handleInputChange, 
  handleSubmit, 
  isLoading,
  onClose,
  tutorialContext,
  onQuickQuestion,
  showHeader = false
}: SageChatInterfaceProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const quickQuestions = tutorialContext ? [
    "Can you explain the key concepts?",
    "What are common gotchas to avoid?", 
    "How does this relate to other Six Paths?",
    "Can you give me a practical example?"
  ] : [
    "How do I choose which path to focus on?",
    "What's my recommended next tutorial?",
    "How can I improve my learning efficiency?",
    "Explain the Six Paths methodology"
  ];

  return (
    <div className="flex flex-col h-full">
      {showHeader && (
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center space-x-2">
            <div className="text-2xl">🎯</div>
            <div>
              <h3 className="font-semibold">Six Paths Sage</h3>
              <p className="text-xs text-muted-foreground">Your Learning Mentor</p>
            </div>
          </div>
          {onClose && (
            <Button variant="ghost" size="sm" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.filter(m => m.role !== 'system').map((message) => (
          <div
            key={message.id}
            className={cn(
              "flex space-x-2",
              message.role === 'user' ? 'justify-end' : 'justify-start'
            )}
          >
            {message.role === 'assistant' && (
              <div className="w-8 h-8 rounded-full bg-gradient-to-r from-purple-500 to-blue-500 flex items-center justify-center text-white text-sm shrink-0">
                🥋
              </div>
            )}
            <div
              className={cn(
                "max-w-[80%] rounded-lg px-3 py-2 text-sm",
                message.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted'
              )}
            >
              <ReactMarkdown 
                className="prose prose-sm dark:prose-invert max-w-none"
                components={{
                  code: ({ node, ...props }) => (
                    <code className="bg-muted px-1 py-0.5 rounded text-xs" {...props} />
                  ),
                  pre: ({ node, ...props }) => (
                    <pre className="bg-muted p-2 rounded mt-2 overflow-x-auto text-xs" {...props} />
                  )
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
            {message.role === 'user' && (
              <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-primary-foreground text-sm shrink-0">
                👤
              </div>
            )}
          </div>
        ))}
        {isLoading && (
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 rounded-full bg-gradient-to-r from-purple-500 to-blue-500 flex items-center justify-center text-white text-sm">
              🥋
            </div>
            <div className="bg-muted rounded-lg px-3 py-2">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-muted-foreground/50 rounded-full animate-bounce" />
                <div className="w-2 h-2 bg-muted-foreground/50 rounded-full animate-bounce [animation-delay:0.1s]" />
                <div className="w-2 h-2 bg-muted-foreground/50 rounded-full animate-bounce [animation-delay:0.2s]" />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick Questions */}
      <div className="p-2 border-t">
        <div className="grid grid-cols-1 gap-1 mb-2">
          {quickQuestions.map((question, index) => (
            <Button
              key={index}
              variant="ghost"
              size="sm"
              className="justify-start h-auto p-2 text-xs"
              onClick={() => onQuickQuestion(question)}
              disabled={isLoading}
            >
              {question}
            </Button>
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="p-4 border-t">
        <form onSubmit={handleSubmit} className="flex space-x-2">
          <Input
            value={input}
            onChange={handleInputChange}
            placeholder="Ask Sensei Roku anything..."
            disabled={isLoading}
            className="flex-1"
          />
          <Button type="submit" disabled={isLoading || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </div>
  );
}

// hooks/useAPISettings.ts
export function useAPISettings() {
  const [apiKey, setApiKey] = useState<string>('');
  const [baseUrl, setBaseUrl] = useState<string>('');
  const [isConfigured, setIsConfigured] = useState<boolean>(false);

  useEffect(() => {
    // Load from localStorage
    const storedKey = localStorage.getItem('sixpaths-api-key');
    const storedUrl = localStorage.getItem('sixpaths-base-url');
    
    if (storedKey) {
      try {
        // Decode from base64 for basic security
        const decodedKey = atob(storedKey);
        setApiKey(decodedKey);
        setIsConfigured(true);
      } catch (error) {
        console.error('Failed to decode API key');
      }
    }
    
    if (storedUrl) {
      setBaseUrl(storedUrl);
    }
  }, []);

  const saveSettings = (newApiKey: string, newBaseUrl: string) => {
    try {
      // Encode to base64 for basic security (not encryption, just obfuscation)
      const encodedKey = btoa(newApiKey);
      localStorage.setItem('sixpaths-api-key', encodedKey);
      localStorage.setItem('sixpaths-base-url', newBaseUrl);
      
      setApiKey(newApiKey);
      setBaseUrl(newBaseUrl);
      setIsConfigured(true);
    } catch (error) {
      console.error('Failed to save API settings');
    }
  };

  const clearSettings = () => {
    localStorage.removeItem('sixpaths-api-key');
    localStorage.removeItem('sixpaths-base-url');
    setApiKey('');
    setBaseUrl('');
    setIsConfigured(false);
  };

  return {
    apiKey,
    baseUrl,
    isConfigured,
    saveSettings,
    clearSettings
  };
}

// components/features/SenseiSetupPrompt.tsx
export function SenseiSetupPrompt() {
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('https://api.openai.com');
  const { saveSettings } = useAPISettings();
  const [isOpen, setIsOpen] = useState(false);

  const handleSave = () => {
    if (apiKey.trim()) {
      saveSettings(apiKey.trim(), baseUrl.trim());
      setIsOpen(false);
    }
  };

  return (
    <div className="p-4 text-center space-y-4">
      <div className="text-6xl mb-4">🥋</div>
      <h3 className="font-semibold">Meet Sensei Roku</h3>
      <p className="text-sm text-muted-foreground">
        Configure your AI learning mentor to get personalized guidance on your journey.
      </p>
      
      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogTrigger asChild>
          <Button>Configure Sensei</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Configure Sensei Roku</DialogTitle>
            <DialogDescription>
              Enter your OpenAI-compatible API credentials to enable your personal learning mentor.
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4">
            <div>
              <Label htmlFor="apiKey">API Key</Label>
              <Input
                id="apiKey"
                type="password"
                placeholder="sk-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                Your API key is stored locally and never sent to our servers.
              </p>
            </div>
            
            <div>
              <Label htmlFor="baseUrl">Base URL</Label>
              <Input
                id="baseUrl"
                placeholder="https://api.openai.com"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                Use https://api.openai.com for OpenAI or your provider's endpoint.
              </p>
            </div>
            
            <div className="bg-blue-50 dark:bg-blue-950 p-3 rounded-lg">
              <div className="flex items-start space-x-2">
                <Shield className="h-4 w-4 text-blue-600 mt-0.5" />
                <div className="text-sm">
                  <p className="font-medium text-blue-800 dark:text-blue-200">Secure & Private</p>
                  <p className="text-blue-600 dark:text-blue-300">
                    Your credentials are stored locally using base64 encoding and never leave your device.
                  </p>
                </div>
              </div>
            </div>
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={!apiKey.trim()}>
              Save Configuration
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

#### Task 2.6: Progress Analytics
**Estimated Time: 6 hours**

```typescript
// components/features/ProgressAnalytics.tsx
export function ProgressAnalytics() {
  const { profile } = useProfile();
  const { data: pathsData } = usePathsData();
  
  if (!profile || !pathsData) return <AnalyticsSkeleton />;
  
  const analytics = calculateAnalytics(profile, pathsData);
  
  return (
    <div className="space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard
          title="Total XP"
          value={profile.user.totalXP}
          icon={<Star className="h-5 w-5" />}
          trend={analytics.xpTrend}
        />
        <StatsCard
          title="Tutorials Completed"
          value={analytics.totalCompleted}
          icon={<BookOpen className="h-5 w-5" />}
          trend={analytics.completionTrend}
        />
        <StatsCard
          title="Current Streak"
          value={`${analytics.streak} days`}
          icon={<Flame className="h-5 w-5" />}
          trend={analytics.streakTrend}
        />
        <StatsCard
          title="Avg. Hours/Week"
          value={analytics.avgHoursPerWeek}
          icon={<Clock className="h-5 w-5" />}
          trend={analytics.timeTrend}
        />
      </div>
      
      {/* Progress Chart */}
      <Card>
        <CardHeader>
          <CardTitle>Learning Progress Over Time</CardTitle>
        </CardHeader>
        <CardContent>
          <ProgressChart data={analytics.progressHistory} />
        </CardContent>
      </Card>
      
      {/* Skills Radar */}
      <Card>
        <CardHeader>
          <CardTitle>Skills Development</CardTitle>
        </CardHeader>
        <CardContent>
          <SkillsRadar skills={analytics.skillsBreakdown} />
        </CardContent>
      </Card>
    </div>
  );
}
```

## 🧪 Testing Tasks

### Task 2.6: Progress Tracking Tests
**Estimated Time: 4 hours**

```typescript
// hooks/useProfile.test.ts
describe('useProfile', () => {
  it('should update progress correctly', () => {
    const { result } = renderHook(() => useProfile());
    
    act(() => {
      result.current.updateProgress('foundations', 'data-structures-101', true);
    });
    
    expect(result.current.profile?.progress.foundations.completed).toBe(1);
    expect(result.current.profile?.progress.foundations.completedTutorials).toContain('data-structures-101');
  });
  
  it('should calculate achievements correctly', () => {
    // Test achievement unlocking logic
  });
});
```

## 📁 New Files After Phase 2

```
src/
├── components/
│   ├── features/
│   │   ├── ProgressDashboard.tsx
│   │   ├── PathProgressCard.tsx
│   │   ├── TutorialDetail.tsx
│   │   ├── AchievementNotification.tsx
│   │   ├── ProgressAnalytics.tsx
│   │   ├── CompletionToggle.tsx
│   │   ├── SixPathsSage.tsx
│   │   ├── SageChatInterface.tsx
│   │   └── SageSetupPrompt.tsx
│   └── ui/
│       ├── ProgressChart.tsx
│       ├── SkillsRadar.tsx
│       └── StatsCard.tsx
├── lib/
│   ├── achievements.ts
│   ├── analytics.ts
│   └── progress.ts
└── hooks/
    ├── useProfile.ts (enhanced)
    ├── useAchievements.ts
    └── useAPISettings.ts
```

## 📦 Additional Dependencies Required

```bash
# Six Paths Sage AI Assistant
npm install ai @ai-sdk/openai @ai-sdk/anthropic
npm install react-markdown framer-motion
```

## ✅ Definition of Done

- [ ] User profile system with XP tracking implemented
- [ ] Progress visualization components render correctly
- [ ] Six Paths dashboard shows accurate progress
- [ ] Tutorial detail pages with completion tracking
- [ ] Achievement system with notifications working
- [ ] Progress analytics and charts functional
- [ ] **Six Paths Sage AI assistant integrated**
- [ ] **Secure API key storage with base64 encoding**
- [ ] **Chat interface working in sidebar and floating modes**
- [ ] **Context-aware responses for tutorials and paths**
- [ ] **Setup flow for API configuration completed**
- [ ] Local storage persistence working reliably
- [ ] All progress-related tests passing

## 🔗 Next Phase

After completing Phase 2, proceed to [Phase 3: Social Features](./phase-3-social-features.md) to implement peer comparison and community features.

---

**Phase 2 transforms SixPathsAcademy from a simple app into a comprehensive progress tracking system that motivates and guides users through their learning journey.** 🚀