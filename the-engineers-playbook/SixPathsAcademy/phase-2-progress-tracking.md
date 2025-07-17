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

      {/* Tutorial Content Link */}
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

#### Task 2.5: Progress Analytics
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
│   │   └── CompletionToggle.tsx
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
    └── useAchievements.ts
```

## ✅ Definition of Done

- [ ] User profile system with XP tracking implemented
- [ ] Progress visualization components render correctly
- [ ] Six Paths dashboard shows accurate progress
- [ ] Tutorial detail pages with completion tracking
- [ ] Achievement system with notifications working
- [ ] Progress analytics and charts functional
- [ ] Local storage persistence working reliably
- [ ] All progress-related tests passing

## 🔗 Next Phase

After completing Phase 2, proceed to [Phase 3: Social Features](./phase-3-social-features.md) to implement peer comparison and community features.

---

**Phase 2 transforms SixPathsAcademy from a simple app into a comprehensive progress tracking system that motivates and guides users through their learning journey.** 🚀