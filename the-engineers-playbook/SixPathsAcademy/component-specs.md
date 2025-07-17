# Component Specifications

> **Complete React component specifications and implementation guidelines for SixPathsAcademy**

## 📋 Overview

This document provides detailed specifications for all React components used in the SixPathsAcademy application. It includes component hierarchies, prop interfaces, styling guidelines, and implementation patterns.

## 🏗️ Component Architecture

### Component Hierarchy

```
App
├── Layout Components
│   ├── RootLayout
│   ├── Navbar (Desktop/Mobile)
│   ├── Sidebar
│   └── Footer
├── Page Components
│   ├── DashboardPage
│   ├── PathDetailPage
│   ├── TutorialDetailPage
│   ├── ProfilePage
│   ├── SocialPage
│   ├── LeaderboardPage
│   └── SettingsPage
├── Feature Components
│   ├── Progress Tracking
│   ├── Social Features
│   ├── Achievement System
│   ├── Export/Import
│   └── Help System
└── UI Components
    ├── Base Components (ShadCN)
    ├── Custom Components
    └── Utility Components
```

## 🎨 Design System

### Color Palette

```typescript
// lib/design-tokens.ts
export const colors = {
  primary: {
    50: '#eff6ff',
    100: '#dbeafe',
    500: '#3b82f6',
    600: '#2563eb',
    900: '#1e3a8a'
  },
  secondary: {
    50: '#f5f3ff',
    100: '#ede9fe',
    500: '#8b5cf6',
    600: '#7c3aed',
    900: '#581c87'
  },
  success: '#10b981',
  warning: '#f59e0b',
  error: '#ef4444',
  muted: '#6b7280'
};

export const spacing = {
  xs: '0.25rem',
  sm: '0.5rem',
  md: '1rem',
  lg: '1.5rem',
  xl: '2rem',
  '2xl': '3rem'
};

export const typography = {
  sizes: {
    xs: '0.75rem',
    sm: '0.875rem',
    base: '1rem',
    lg: '1.125rem',
    xl: '1.25rem',
    '2xl': '1.5rem',
    '3xl': '1.875rem',
    '4xl': '2.25rem'
  },
  weights: {
    normal: '400',
    medium: '500',
    semibold: '600',
    bold: '700'
  }
};
```

### Component Styling Guidelines

```typescript
// lib/component-styles.ts
export const componentStyles = {
  card: {
    base: 'rounded-lg border border-border bg-card text-card-foreground shadow-sm',
    hover: 'hover:shadow-md transition-shadow duration-200',
    focus: 'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2'
  },
  button: {
    base: 'inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
    variants: {
      default: 'bg-primary text-primary-foreground hover:bg-primary/90',
      outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground',
      ghost: 'hover:bg-accent hover:text-accent-foreground'
    },
    sizes: {
      sm: 'h-9 rounded-md px-3',
      md: 'h-10 px-4 py-2',
      lg: 'h-11 rounded-md px-8'
    }
  }
};
```

## 📱 Layout Components

### RootLayout

**Purpose**: Main application layout wrapper with theme provider and navigation

```typescript
// components/layout/RootLayout.tsx
interface RootLayoutProps {
  children: React.ReactNode;
}

export function RootLayout({ children }: RootLayoutProps) {
  const { theme } = useTheme();
  const { isOffline } = useOfflineSupport();
  
  return (
    <div className={`min-h-screen bg-background font-sans antialiased ${theme}`}>
      <ThemeProvider>
        <ToastProvider>
          <div className="relative flex min-h-screen flex-col">
            <SiteHeader />
            <main className="flex-1">
              <div className="container mx-auto px-4 py-8">
                <ErrorBoundary>
                  {children}
                </ErrorBoundary>
              </div>
            </main>
            <SiteFooter />
          </div>
          {isOffline && <OfflineIndicator />}
          <ToastContainer />
        </ToastProvider>
      </ThemeProvider>
    </div>
  );
}

// Styling
const styles = {
  container: 'min-h-screen bg-background font-sans antialiased',
  main: 'flex-1 container mx-auto px-4 py-8',
  content: 'max-w-7xl mx-auto'
};
```

### Navbar Components

**Purpose**: Navigation header with responsive behavior

```typescript
// components/layout/Navbar.tsx
interface NavbarProps {
  className?: string;
}

export function Navbar({ className }: NavbarProps) {
  const { profile } = useProfile();
  const { isMobile } = useResponsive();
  
  return (
    <header className={cn("sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60", className)}>
      <div className="container flex h-16 items-center">
        <MainNav />
        <div className="ml-auto flex items-center space-x-4">
          <SearchButton />
          <ThemeToggle />
          <UserNav profile={profile} />
        </div>
      </div>
    </header>
  );
}

// components/layout/MainNav.tsx
interface MainNavProps {
  className?: string;
}

export function MainNav({ className }: MainNavProps) {
  const pathname = useRouter().state.location.pathname;
  
  const routes = [
    { href: "/", label: "Dashboard", icon: LayoutDashboard },
    { href: "/paths", label: "Six Paths", icon: BookOpen },
    { href: "/social", label: "Social", icon: Users },
    { href: "/leaderboard", label: "Leaderboard", icon: Trophy }
  ];
  
  return (
    <nav className={cn("flex items-center space-x-6", className)}>
      <Link to="/" className="flex items-center space-x-2">
        <div className="text-2xl">🎯</div>
        <span className="hidden font-bold sm:inline-block">SixPathsAcademy</span>
      </Link>
      
      <div className="hidden md:flex space-x-6">
        {routes.map((route) => (
          <Link
            key={route.href}
            to={route.href}
            className={cn(
              "flex items-center space-x-1 text-sm font-medium transition-colors hover:text-primary",
              pathname === route.href
                ? "text-primary"
                : "text-muted-foreground"
            )}
          >
            <route.icon className="h-4 w-4" />
            <span>{route.label}</span>
          </Link>
        ))}
      </div>
    </nav>
  );
}

// Mobile Navigation
interface MobileNavProps {
  isOpen: boolean;
  onToggle: (open: boolean) => void;
}

export function MobileNav({ isOpen, onToggle }: MobileNavProps) {
  const routes = [
    { href: "/", label: "Dashboard", icon: LayoutDashboard },
    { href: "/paths", label: "Six Paths", icon: BookOpen },
    { href: "/social", label: "Social", icon: Users },
    { href: "/leaderboard", label: "Leaderboard", icon: Trophy },
    { href: "/settings", label: "Settings", icon: Settings }
  ];
  
  return (
    <div className="md:hidden">
      <Sheet open={isOpen} onOpenChange={onToggle}>
        <SheetContent side="left" className="w-[300px] sm:w-[400px]">
          <nav className="flex flex-col space-y-4">
            {routes.map((route) => (
              <Link
                key={route.href}
                to={route.href}
                className="flex items-center space-x-2 text-lg font-medium"
                onClick={() => onToggle(false)}
              >
                <route.icon className="h-5 w-5" />
                <span>{route.label}</span>
              </Link>
            ))}
          </nav>
        </SheetContent>
      </Sheet>
    </div>
  );
}
```

## 🎯 Page Components

### DashboardPage

**Purpose**: Main dashboard showing progress overview and quick actions

```typescript
// components/pages/DashboardPage.tsx
interface DashboardPageProps {
  className?: string;
}

export function DashboardPage({ className }: DashboardPageProps) {
  const { profile, isLoading } = useProfile();
  const { data: pathsData } = usePathsData();
  const { achievements } = useAchievements();
  
  if (isLoading) {
    return <DashboardSkeleton />;
  }
  
  if (!profile) {
    return <OnboardingFlow />;
  }
  
  return (
    <div className={cn("space-y-8", className)}>
      <WelcomeHeader profile={profile} />
      <ProgressOverview profile={profile} pathsData={pathsData} />
      <PathsGrid paths={pathsData?.paths} progress={profile.progress} />
      <RecentActivity profile={profile} />
      <AchievementsList achievements={achievements} />
    </div>
  );
}

// Sub-components
interface WelcomeHeaderProps {
  profile: UserProfile;
}

export function WelcomeHeader({ profile }: WelcomeHeaderProps) {
  const timeOfDay = getTimeOfDay();
  
  return (
    <div className="text-center space-y-4">
      <h1 className="text-4xl font-bold bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent">
        {timeOfDay}, {profile.user.name}! 🎯
      </h1>
      <div className="flex justify-center items-center space-x-4">
        <LevelBadge 
          level={profile.user.currentLevel} 
          xp={profile.user.totalXP} 
        />
        <StreakBadge streak={profile.user.streak} />
      </div>
    </div>
  );
}
```

### PathDetailPage

**Purpose**: Detailed view of a specific learning path

```typescript
// components/pages/PathDetailPage.tsx
interface PathDetailPageProps {
  pathId: string;
}

export function PathDetailPage({ pathId }: PathDetailPageProps) {
  const { data: pathsData } = usePathsData();
  const { profile } = useProfile();
  
  const path = pathsData?.paths[pathId];
  const progress = profile?.progress[pathId];
  
  if (!path) {
    return <PathNotFound pathId={pathId} />;
  }
  
  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <PathHeader path={path} progress={progress} />
      <PathStats path={path} progress={progress} />
      <TutorialsList 
        tutorials={path.tutorials} 
        pathId={pathId}
        progress={progress}
      />
      <PathRecommendations path={path} />
    </div>
  );
}

// Sub-components
interface PathHeaderProps {
  path: Path;
  progress?: PathProgress;
}

export function PathHeader({ path, progress }: PathHeaderProps) {
  const completionPercentage = progress 
    ? (progress.completed / progress.total) * 100 
    : 0;
  
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div className="space-y-4">
          <div className="flex items-center space-x-4">
            <div className="text-6xl">{path.icon}</div>
            <div>
              <h1 className="text-4xl font-bold">{path.name}</h1>
              <p className="text-xl text-muted-foreground mt-2">
                {path.description}
              </p>
            </div>
          </div>
          
          <div className="flex items-center space-x-4">
            <Badge variant={getDifficultyVariant(path.difficulty)}>
              {path.difficulty}
            </Badge>
            <Badge variant="secondary">
              <Clock className="h-3 w-3 mr-1" />
              {path.estimatedWeeks} weeks
            </Badge>
            <Badge variant="secondary">
              <BookOpen className="h-3 w-3 mr-1" />
              {path.tutorials.length} tutorials
            </Badge>
          </div>
        </div>
        
        <div className="text-right">
          <div className="text-3xl font-bold">
            {progress?.completed || 0}/{progress?.total || path.tutorials.length}
          </div>
          <div className="text-sm text-muted-foreground">Completed</div>
        </div>
      </div>
      
      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <span>Progress</span>
          <span>{Math.round(completionPercentage)}%</span>
        </div>
        <Progress value={completionPercentage} className="h-3" />
      </div>
    </div>
  );
}
```

## 🎨 Feature Components

### Progress Tracking Components

```typescript
// components/features/ProgressCard.tsx
interface ProgressCardProps {
  title: string;
  value: number;
  total?: number;
  icon: React.ComponentType<{ className?: string }>;
  trend?: 'up' | 'down' | 'stable';
  className?: string;
}

export function ProgressCard({ 
  title, 
  value, 
  total, 
  icon: Icon, 
  trend,
  className 
}: ProgressCardProps) {
  const percentage = total ? (value / total) * 100 : 0;
  
  return (
    <Card className={cn("p-6", className)}>
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <div className="flex items-center space-x-2">
            <p className="text-2xl font-bold">
              {value}
              {total && <span className="text-lg text-muted-foreground">/{total}</span>}
            </p>
            {trend && <TrendIndicator trend={trend} />}
          </div>
        </div>
        <div className="h-12 w-12 bg-primary/10 rounded-full flex items-center justify-center">
          <Icon className="h-6 w-6 text-primary" />
        </div>
      </div>
      {total && (
        <div className="mt-4 space-y-2">
          <Progress value={percentage} className="h-2" />
          <p className="text-xs text-muted-foreground text-right">
            {Math.round(percentage)}% complete
          </p>
        </div>
      )}
    </Card>
  );
}

// components/features/PathProgressCard.tsx
interface PathProgressCardProps {
  path: Path;
  progress: PathProgress;
  onPathClick?: () => void;
  className?: string;
}

export function PathProgressCard({ 
  path, 
  progress, 
  onPathClick,
  className 
}: PathProgressCardProps) {
  const completionPercentage = (progress.completed / progress.total) * 100;
  const isCompleted = progress.completed === progress.total;
  
  return (
    <Card 
      className={cn(
        "relative overflow-hidden cursor-pointer transition-all hover:shadow-lg",
        isCompleted && "ring-2 ring-green-500",
        className
      )}
      onClick={onPathClick}
    >
      <CardHeader className="pb-4">
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
              <CardDescription className="line-clamp-2">
                {path.description}
              </CardDescription>
            </div>
          </div>
          <Badge variant={getDifficultyVariant(path.difficulty)}>
            {path.difficulty}
          </Badge>
        </div>
      </CardHeader>
      
      <CardContent className="space-y-4">
        <div className="flex justify-between text-sm">
          <span>Progress</span>
          <span>{progress.completed}/{progress.total}</span>
        </div>
        
        <Progress 
          value={completionPercentage} 
          className={cn("h-2", isCompleted && "bg-green-100")}
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
      </CardContent>
    </Card>
  );
}
```

### Social Components

```typescript
// components/features/PeerCard.tsx
interface PeerCardProps {
  peer: ExternalProfile;
  myProfile?: UserProfile;
  onCompare?: () => void;
  onFavorite?: () => void;
  isFavorite?: boolean;
  className?: string;
}

export function PeerCard({ 
  peer, 
  myProfile, 
  onCompare, 
  onFavorite, 
  isFavorite,
  className 
}: PeerCardProps) {
  const { profile } = peer;
  const completedPaths = Object.values(profile.progress).filter(
    p => p.completed === p.total
  ).length;
  
  return (
    <Card className={cn("p-6 hover:shadow-lg transition-shadow", className)}>
      <div className="flex items-start justify-between">
        <div className="flex items-center space-x-4">
          <Avatar className="h-12 w-12">
            <AvatarImage src={`https://github.com/${peer.username}.png`} />
            <AvatarFallback>{peer.username[0]?.toUpperCase()}</AvatarFallback>
          </Avatar>
          <div>
            <h3 className="font-semibold">{profile.user.name}</h3>
            <p className="text-sm text-muted-foreground">@{peer.username}</p>
            <div className="flex items-center space-x-4 mt-2">
              <div className="flex items-center space-x-1">
                <Star className="h-3 w-3 text-yellow-500" />
                <span className="text-sm">{profile.user.totalXP} XP</span>
              </div>
              <div className="flex items-center space-x-1">
                <Trophy className="h-3 w-3 text-green-500" />
                <span className="text-sm">{completedPaths}/6 paths</span>
              </div>
            </div>
          </div>
        </div>
        
        <div className="flex items-center space-x-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onFavorite}
            className={cn(isFavorite && "bg-red-50 text-red-600")}
          >
            <Heart className={cn("h-4 w-4", isFavorite && "fill-current")} />
          </Button>
          <Button variant="outline" size="sm" onClick={onCompare}>
            <BarChart3 className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={peer.siteUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="h-4 w-4" />
            </a>
          </Button>
        </div>
      </div>
    </Card>
  );
}

// components/features/ProgressComparison.tsx
interface ProgressComparisonProps {
  myProfile: UserProfile;
  peerProfile: ExternalProfile;
  className?: string;
}

export function ProgressComparison({ 
  myProfile, 
  peerProfile,
  className 
}: ProgressComparisonProps) {
  const comparisonData = useMemo(() => {
    return calculateComparison(myProfile, peerProfile);
  }, [myProfile, peerProfile]);
  
  if (!peerProfile.isValid) {
    return (
      <Card className={cn("p-8 text-center", className)}>
        <div className="text-muted-foreground">
          Unable to load peer's progress data
        </div>
      </Card>
    );
  }
  
  return (
    <div className={cn("space-y-6", className)}>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center space-x-2">
            <BarChart3 className="h-5 w-5" />
            <span>Progress Comparison</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">
                {myProfile.user.totalXP}
              </div>
              <div className="text-sm text-muted-foreground">Your XP</div>
            </div>
            
            <div className="text-center">
              <div className="text-lg font-semibold">vs</div>
              <div className="text-sm text-muted-foreground">
                {comparisonData.xpDifference > 0 ? (
                  <span className="text-green-600">
                    +{comparisonData.xpDifference} ahead
                  </span>
                ) : comparisonData.xpDifference < 0 ? (
                  <span className="text-red-600">
                    {Math.abs(comparisonData.xpDifference)} behind
                  </span>
                ) : (
                  <span className="text-muted-foreground">Tied</span>
                )}
              </div>
            </div>
            
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-600">
                {peerProfile.profile.user.totalXP}
              </div>
              <div className="text-sm text-muted-foreground">
                {peerProfile.profile.user.name}'s XP
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
      
      <Card>
        <CardHeader>
          <CardTitle>Path-by-Path Comparison</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-6">
            {comparisonData.paths.map(path => (
              <PathComparisonRow
                key={path.pathId}
                path={path}
                myProfile={myProfile}
                peerProfile={peerProfile}
              />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
```

## 🔧 UI Components

### Custom UI Components

```typescript
// components/ui/AnimatedCard.tsx
interface AnimatedCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}

export function AnimatedCard({ 
  children, 
  delay = 0, 
  className, 
  ...props 
}: AnimatedCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay }}
      className={cn("card-base", className)}
      {...props}
    >
      {children}
    </motion.div>
  );
}

// components/ui/LoadingSpinner.tsx
interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
}

export function LoadingSpinner({ size = 'md', className }: LoadingSpinnerProps) {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-6 w-6',
    lg: 'h-8 w-8',
    xl: 'h-12 w-12'
  };
  
  return (
    <div className={cn("flex items-center justify-center", className)}>
      <div className={cn(
        "animate-spin rounded-full border-2 border-primary border-t-transparent",
        sizeClasses[size]
      )} />
    </div>
  );
}

// components/ui/ProgressBar.tsx
interface ProgressBarProps {
  value: number;
  max?: number;
  className?: string;
  animated?: boolean;
  showLabel?: boolean;
}

export function ProgressBar({ 
  value, 
  max = 100, 
  className, 
  animated = false,
  showLabel = false 
}: ProgressBarProps) {
  const percentage = Math.min((value / max) * 100, 100);
  
  return (
    <div className={cn("space-y-2", className)}>
      {showLabel && (
        <div className="flex justify-between text-sm">
          <span>Progress</span>
          <span>{value}/{max}</span>
        </div>
      )}
      <div className="h-2 bg-muted rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full bg-primary rounded-full transition-all duration-300",
            animated && "animate-pulse"
          )}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

// components/ui/StatusBadge.tsx
interface StatusBadgeProps {
  status: 'completed' | 'in-progress' | 'not-started';
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const statusConfig = {
    completed: {
      label: 'Completed',
      className: 'bg-green-100 text-green-800',
      icon: CheckCircle
    },
    'in-progress': {
      label: 'In Progress',
      className: 'bg-blue-100 text-blue-800',
      icon: Clock
    },
    'not-started': {
      label: 'Not Started',
      className: 'bg-gray-100 text-gray-800',
      icon: Circle
    }
  };
  
  const config = statusConfig[status];
  const Icon = config.icon;
  
  return (
    <Badge className={cn(config.className, className)}>
      <Icon className="h-3 w-3 mr-1" />
      {config.label}
    </Badge>
  );
}
```

### Skeleton Components

```typescript
// components/ui/Skeleton.tsx
interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div className={cn("animate-pulse bg-muted rounded", className)} />
  );
}

// components/ui/CardSkeleton.tsx
export function CardSkeleton() {
  return (
    <Card className="p-6">
      <div className="flex items-center space-x-4">
        <Skeleton className="h-12 w-12 rounded-full" />
        <div className="space-y-2 flex-1">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
      <div className="mt-4 space-y-3">
        <Skeleton className="h-2 w-full" />
        <div className="flex justify-between">
          <Skeleton className="h-3 w-1/4" />
          <Skeleton className="h-3 w-1/4" />
        </div>
      </div>
    </Card>
  );
}

// components/ui/PageSkeleton.tsx
export function PageSkeleton() {
  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <Skeleton className="h-8 w-1/3 mx-auto" />
        <Skeleton className="h-4 w-1/2 mx-auto" />
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {[...Array(6)].map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}
```

## 🎭 Animation Components

```typescript
// components/ui/FadeIn.tsx
interface FadeInProps {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}

export function FadeIn({ children, delay = 0, className }: FadeInProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5, delay }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

// components/ui/SlideIn.tsx
interface SlideInProps {
  children: React.ReactNode;
  direction?: 'left' | 'right' | 'up' | 'down';
  delay?: number;
  className?: string;
}

export function SlideIn({ 
  children, 
  direction = 'up', 
  delay = 0, 
  className 
}: SlideInProps) {
  const directionConfig = {
    up: { y: 20 },
    down: { y: -20 },
    left: { x: -20 },
    right: { x: 20 }
  };
  
  return (
    <motion.div
      initial={{ opacity: 0, ...directionConfig[direction] }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={{ duration: 0.3, delay }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

// components/ui/StaggeredList.tsx
interface StaggeredListProps {
  children: React.ReactNode[];
  className?: string;
}

export function StaggeredList({ children, className }: StaggeredListProps) {
  return (
    <div className={className}>
      {children.map((child, index) => (
        <SlideIn key={index} delay={index * 0.1}>
          {child}
        </SlideIn>
      ))}
    </div>
  );
}
```

## 📱 Responsive Utilities

```typescript
// hooks/useResponsive.ts
export function useResponsive() {
  const [screenSize, setScreenSize] = useState<'mobile' | 'tablet' | 'desktop'>('desktop');
  
  useEffect(() => {
    const checkScreenSize = () => {
      const width = window.innerWidth;
      if (width < 768) {
        setScreenSize('mobile');
      } else if (width < 1024) {
        setScreenSize('tablet');
      } else {
        setScreenSize('desktop');
      }
    };
    
    checkScreenSize();
    window.addEventListener('resize', checkScreenSize);
    
    return () => window.removeEventListener('resize', checkScreenSize);
  }, []);
  
  return {
    screenSize,
    isMobile: screenSize === 'mobile',
    isTablet: screenSize === 'tablet',
    isDesktop: screenSize === 'desktop'
  };
}

// components/ui/ResponsiveGrid.tsx
interface ResponsiveGridProps {
  children: React.ReactNode;
  className?: string;
}

export function ResponsiveGrid({ children, className }: ResponsiveGridProps) {
  const { isMobile, isTablet } = useResponsive();
  
  const getGridClasses = () => {
    if (isMobile) return 'grid-cols-1';
    if (isTablet) return 'grid-cols-2';
    return 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3';
  };
  
  return (
    <div className={cn('grid gap-6', getGridClasses(), className)}>
      {children}
    </div>
  );
}
```

## 🧪 Component Testing

```typescript
// components/ui/ProgressCard.test.tsx
import { render, screen } from '@testing-library/react';
import { ProgressCard } from './ProgressCard';
import { Star } from 'lucide-react';

describe('ProgressCard', () => {
  it('renders correctly with basic props', () => {
    render(
      <ProgressCard
        title="Total XP"
        value={150}
        icon={Star}
      />
    );
    
    expect(screen.getByText('Total XP')).toBeInTheDocument();
    expect(screen.getByText('150')).toBeInTheDocument();
  });
  
  it('shows progress when total is provided', () => {
    render(
      <ProgressCard
        title="Tutorials"
        value={5}
        total={10}
        icon={Star}
      />
    );
    
    expect(screen.getByText('5/10')).toBeInTheDocument();
    expect(screen.getByText('50% complete')).toBeInTheDocument();
  });
  
  it('displays trend indicator when provided', () => {
    render(
      <ProgressCard
        title="XP"
        value={200}
        icon={Star}
        trend="up"
      />
    );
    
    expect(screen.getByTestId('trend-indicator')).toBeInTheDocument();
  });
});
```

## 📚 Style Guide

### Component Naming Conventions

- **PascalCase** for component names
- **camelCase** for prop names
- **kebab-case** for CSS classes
- **SCREAMING_SNAKE_CASE** for constants

### File Organization

```
components/
├── ui/           # Reusable UI components
├── features/     # Feature-specific components
├── layout/       # Layout components
├── pages/        # Page components
└── forms/        # Form components
```

### Props Interface Standards

```typescript
// Always extend HTML attributes when possible
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'outline' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
}

// Use optional className prop
interface ComponentProps {
  className?: string;
  children?: React.ReactNode;
}

// Use discriminated unions for variants
interface CardProps {
  variant: 'default' | 'outline' | 'filled';
  className?: string;
}
```

---

**This comprehensive component specification ensures consistent, maintainable, and scalable React components throughout the SixPathsAcademy application.** 🚀

*All components follow modern React patterns with TypeScript for type safety and accessibility best practices.*