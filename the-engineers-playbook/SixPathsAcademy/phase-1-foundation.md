# Phase 1: Foundation (Weeks 1-2)

> **Establish the core application structure with TanStack Router, data models, and basic UI components**

## 🎯 Phase Goals

- Set up React application with TanStack Router
- Define TypeScript interfaces for all data models
- Create basic routing structure and layout components
- Implement data loading and state management
- Build foundational UI components with ShadCN

## 📋 Tasks Breakdown

### **Week 1: Project Setup & Routing**

#### Task 1.1: Initialize Project Structure
**Estimated Time: 4 hours**

```bash
# Assuming create-tsrouter is already used
npm install @tanstack/react-router @tanstack/router-devtools
npm install tailwindcss @tailwindcss/typography
npm install @radix-ui/react-slot @radix-ui/react-separator
npm install lucide-react class-variance-authority clsx tailwind-merge
```

**Directory Structure:**
```
src/
├── components/
│   ├── ui/           # ShadCN UI components
│   ├── layout/       # Layout components
│   └── features/     # Feature-specific components
├── data/
│   ├── config.json
│   ├── data.json
│   └── profile.json
├── hooks/            # Custom React hooks
├── lib/              # Utilities and helpers
├── routes/           # TanStack Router routes
├── stores/           # State management
└── types/            # TypeScript definitions
```

#### Task 1.2: Configure TanStack Router
**Estimated Time: 6 hours**

**Routes Structure:**
```typescript
// routes/__root.tsx
import { createRootRoute } from '@tanstack/react-router'
import { RootLayout } from '../components/layout/RootLayout'

export const Route = createRootRoute({
  component: RootLayout,
})

// routes/index.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: DashboardPage,
})

// routes/paths/$pathId.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/paths/$pathId',
  component: PathDetailPage,
})

// routes/tutorial/$tutorialId.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/tutorial/$tutorialId',
  component: TutorialDetailPage,
})

// routes/profile.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/profile',
  component: ProfilePage,
})

// routes/leaderboard.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/leaderboard',
  component: LeaderboardPage,
})

// routes/settings.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage,
})
```

#### Task 1.3: TypeScript Interfaces
**Estimated Time: 4 hours**

**Core Types:**
```typescript
// types/index.ts
export interface Config {
  app: {
    name: string;
    version: string;
    description: string;
  };
  sourceRepo: {
    owner: string;
    repo: string;
    branch: string;
  };
  links: {
    tutorialsRepo: string;
    documentation: string;
    community: string;
  };
  features: {
    enablePeerComparison: boolean;
    enableExport: boolean;
    enableSync: boolean;
    enableLeaderboard: boolean;
  };
  ui: {
    theme: 'light' | 'dark';
    primaryColor: string;
    accentColor: string;
  };
}

export interface Path {
  id: string;
  name: string;
  icon: string;
  description: string;
  difficulty: 'beginner' | 'intermediate' | 'advanced';
  estimatedWeeks: number;
  prerequisites: string[];
  tutorials: string[];
  skills: string[];
}

export interface Tutorial {
  id: string;
  title: string;
  pathId: string;
  difficulty: string;
  estimatedHours: number;
  prerequisites: string[];
  skills: string[];
  description: string;
  githubUrl: string;
  nextTutorials: string[];
}

export interface UserProfile {
  user: {
    name: string;
    github: string;
    avatar: string;
    joinDate: string;
    currentLevel: string;
    totalXP: number;
  };
  progress: Record<string, PathProgress>;
  preferences: {
    favoriteDevs: string[];
    notifications: boolean;
    publicProfile: boolean;
  };
  achievements: Achievement[];
}

export interface PathProgress {
  completed: number;
  total: number;
  completedTutorials: string[];
  currentTutorial: string | null;
  startDate: string;
  completionDate: string | null;
  xpEarned: number;
}

export interface Achievement {
  id: string;
  title: string;
  description: string;
  icon: string;
  unlockedAt: string;
  path?: string;
  rarity: 'common' | 'rare' | 'epic' | 'legendary';
}
```

### **Week 2: Data Layer & Basic Components**

#### Task 1.4: Data Loading System
**Estimated Time: 6 hours**

```typescript
// hooks/useData.ts
export function useConfig() {
  const [config, setConfig] = useState<Config | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/data/config.json')
      .then(res => res.json())
      .then(setConfig)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  return { config, loading, error };
}

export function usePathsData() {
  const [data, setData] = useState<{ paths: Record<string, Path>, tutorials: Record<string, Tutorial> } | null>(null);
  // Similar implementation
}

export function useProfile() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  
  useEffect(() => {
    // Load from localStorage or create default
    const stored = localStorage.getItem('codesagemode-profile');
    if (stored) {
      setProfile(JSON.parse(stored));
    } else {
      setProfile(createDefaultProfile());
    }
  }, []);

  const updateProfile = (updates: Partial<UserProfile>) => {
    setProfile(prev => {
      const updated = { ...prev, ...updates };
      localStorage.setItem('codesagemode-profile', JSON.stringify(updated));
      return updated;
    });
  };

  return { profile, updateProfile };
}
```

#### Task 1.5: Layout Components
**Estimated Time: 8 hours**

**Root Layout:**
```typescript
// components/layout/RootLayout.tsx
export function RootLayout() {
  return (
    <div className="min-h-screen bg-background">
      <Navbar />
      <main className="container mx-auto px-4 py-8">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}

// components/layout/Navbar.tsx
export function Navbar() {
  const { profile } = useProfile();
  
  return (
    <nav className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto px-4">
        <div className="flex h-16 items-center justify-between">
          <div className="flex items-center space-x-8">
            <Link to="/" className="text-2xl font-bold">
              🎯 SixPathsAcademy
            </Link>
            <NavigationMenu>
              <NavigationMenuItem>
                <Link to="/paths" className="nav-link">Six Paths</Link>
              </NavigationMenuItem>
              <NavigationMenuItem>
                <Link to="/leaderboard" className="nav-link">Leaderboard</Link>
              </NavigationMenuItem>
            </NavigationMenu>
          </div>
          
          <div className="flex items-center space-x-4">
            <ThemeToggle />
            <UserMenu profile={profile} />
          </div>
        </div>
      </div>
    </nav>
  );
}
```

#### Task 1.6: Basic UI Components
**Estimated Time: 6 hours**

**ShadCN UI Setup:**
```bash
npx shadcn-ui@latest init
npx shadcn-ui@latest add button
npx shadcn-ui@latest add card
npx shadcn-ui@latest add badge
npx shadcn-ui@latest add progress
npx shadcn-ui@latest add avatar
npx shadcn-ui@latest add dropdown-menu
npx shadcn-ui@latest add navigation-menu
npx shadcn-ui@latest add separator
npx shadcn-ui@latest add tabs
```

**Custom Components:**
```typescript
// components/ui/PathCard.tsx
export function PathCard({ path, progress }: { path: Path; progress: PathProgress }) {
  const completionPercentage = (progress.completed / progress.total) * 100;
  
  return (
    <Card className="relative overflow-hidden transition-all hover:shadow-lg">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="text-4xl">{path.icon}</div>
            <div>
              <CardTitle className="text-xl">{path.name}</CardTitle>
              <CardDescription>{path.description}</CardDescription>
            </div>
          </div>
          <Badge variant={path.difficulty === 'beginner' ? 'default' : 'secondary'}>
            {path.difficulty}
          </Badge>
        </div>
      </CardHeader>
      
      <CardContent>
        <div className="space-y-4">
          <div className="flex justify-between text-sm">
            <span>Progress</span>
            <span>{progress.completed}/{progress.total} tutorials</span>
          </div>
          <Progress value={completionPercentage} className="h-2" />
          
          <div className="flex justify-between text-sm text-muted-foreground">
            <span>Est. {path.estimatedWeeks} weeks</span>
            <span>{progress.xpEarned} XP earned</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// components/ui/LevelBadge.tsx
export function LevelBadge({ level, xp }: { level: string; xp: number }) {
  const getLevelColor = (level: string) => {
    switch (level) {
      case 'Code Ninja': return 'bg-blue-500';
      case 'Data Sage': return 'bg-purple-500';
      case 'Systems Master': return 'bg-green-500';
      case 'Six Paths Sage': return 'bg-gradient-to-r from-purple-500 to-blue-500';
      default: return 'bg-gray-500';
    }
  };

  return (
    <Badge className={`${getLevelColor(level)} text-white`}>
      {level} • {xp} XP
    </Badge>
  );
}
```

## 🧪 Testing Tasks

### Task 1.7: Basic Testing Setup
**Estimated Time: 4 hours**

```bash
npm install -D @testing-library/react @testing-library/jest-dom
npm install -D @testing-library/user-event vitest jsdom
```

**Test Examples:**
```typescript
// components/ui/PathCard.test.tsx
import { render, screen } from '@testing-library/react';
import { PathCard } from './PathCard';

describe('PathCard', () => {
  const mockPath = {
    id: 'foundations',
    name: 'Foundations Path',
    icon: '📚',
    description: 'Master the fundamentals',
    difficulty: 'beginner' as const,
    estimatedWeeks: 6,
    prerequisites: [],
    tutorials: ['data-structures-101'],
    skills: ['arrays', 'linked-lists']
  };

  const mockProgress = {
    completed: 2,
    total: 8,
    completedTutorials: ['data-structures-101', 'hashing'],
    currentTutorial: 'sorting',
    startDate: '2024-01-15',
    completionDate: null,
    xpEarned: 150
  };

  it('renders path information correctly', () => {
    render(<PathCard path={mockPath} progress={mockProgress} />);
    
    expect(screen.getByText('Foundations Path')).toBeInTheDocument();
    expect(screen.getByText('Master the fundamentals')).toBeInTheDocument();
    expect(screen.getByText('2/8 tutorials')).toBeInTheDocument();
  });
});
```

## 📁 File Structure After Phase 1

```
src/
├── components/
│   ├── ui/
│   │   ├── PathCard.tsx
│   │   ├── LevelBadge.tsx
│   │   ├── ThemeToggle.tsx
│   │   └── UserMenu.tsx
│   └── layout/
│       ├── RootLayout.tsx
│       ├── Navbar.tsx
│       └── Footer.tsx
├── data/
│   ├── config.json
│   ├── data.json
│   └── profile.json
├── hooks/
│   ├── useData.ts
│   └── useProfile.ts
├── lib/
│   ├── utils.ts
│   └── constants.ts
├── routes/
│   ├── __root.tsx
│   ├── index.tsx
│   ├── paths/
│   │   └── $pathId.tsx
│   ├── tutorial/
│   │   └── $tutorialId.tsx
│   ├── profile.tsx
│   ├── leaderboard.tsx
│   └── settings.tsx
├── stores/
│   └── index.ts
├── types/
│   └── index.ts
└── main.tsx
```

## ✅ Definition of Done

- [ ] React application runs without errors
- [ ] TanStack Router navigation works between all pages
- [ ] Data loading from JSON files functions correctly
- [ ] TypeScript interfaces are defined for all data models
- [ ] Basic UI components render properly with ShadCN
- [ ] Layout components provide consistent structure
- [ ] Dark/light theme toggle works
- [ ] Local storage profile management implemented
- [ ] Basic tests pass for core components

## 🔗 Next Phase

After completing Phase 1, proceed to [Phase 2: Progress Tracking](./phase-2-progress-tracking.md) to implement user profiles and progress visualization.

---

**Phase 1 establishes the foundation for the entire SixPathsAcademy application. Take time to ensure all components are solid before moving to the next phase.** 🚀