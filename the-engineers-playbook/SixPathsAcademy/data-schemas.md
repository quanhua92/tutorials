# Data Schemas & File Structures

> **Complete JSON file structures and TypeScript interfaces for SixPathsAcademy data management**

## 📋 Overview

This document defines all JSON file structures and TypeScript interfaces used throughout the SixPathsAcademy application. These schemas ensure data consistency, type safety, and provide clear contracts for all data operations.

## 🗂️ File Structure

```
data/
├── config.json          # Application configuration
├── data.json            # Core tutorial and path data
├── profile.json         # User profile template
├── metadata.json        # Application metadata
└── schemas/
    ├── config.schema.json
    ├── data.schema.json
    ├── profile.schema.json
    └── ranking.schema.json
```

## 📄 Core Data Files

### 1. config.json

**Purpose**: Application configuration and feature toggles

```json
{
  "app": {
    "name": "SixPathsAcademy",
    "version": "1.0.0",
    "description": "Master software engineering through the Six Paths methodology",
    "author": "SixPathsAcademy Team",
    "license": "MIT",
    "repository": "https://github.com/quanhua92/SixPathsAcademy"
  },
  "sourceRepo": {
    "owner": "quanhua92",
    "repo": "the-engineers-playbook",
    "branch": "main",
    "tutorialsPath": "/tutorials"
  },
  "links": {
    "tutorialsRepo": "https://github.com/quanhua92/the-engineers-playbook",
    "documentation": "https://docs.codesagemode.com",
    "community": "https://discord.gg/codesagemode",
    "support": "https://github.com/quanhua92/SixPathsAcademy/issues"
  },
  "features": {
    "enablePeerComparison": true,
    "enableExport": true,
    "enableSync": true,
    "enableLeaderboard": true,
    "enableOfflineMode": true,
    "enableNotifications": true
  },
  "ui": {
    "theme": "light",
    "primaryColor": "#3b82f6",
    "accentColor": "#8b5cf6",
    "darkMode": true,
    "animations": true
  },
  "performance": {
    "enableLazyLoading": true,
    "enableImageOptimization": true,
    "enableBundleSplitting": true,
    "maxCacheSize": 50
  },
  "analytics": {
    "enabled": false,
    "provider": "none",
    "trackingId": null
  }
}
```

### 2. data.json

**Purpose**: Core tutorial and learning path data

```json
{
  "lastUpdated": "2024-01-20T10:30:00Z",
  "version": "1.0.0",
  "metadata": {
    "totalTutorials": 56,
    "totalPaths": 6,
    "estimatedHours": 280,
    "difficultyLevels": ["beginner", "intermediate", "advanced"],
    "skills": ["algorithms", "data-structures", "systems", "performance"]
  },
  "paths": {
    "foundations": {
      "id": "foundations",
      "name": "Foundations Path",
      "icon": "📚",
      "description": "Master the fundamental concepts of computer science and programming",
      "difficulty": "beginner",
      "estimatedWeeks": 6,
      "estimatedHours": 40,
      "prerequisites": [],
      "color": "#3b82f6",
      "tutorials": [
        "data-structures-algorithms-101",
        "hashing",
        "sorting",
        "searching",
        "trees",
        "graphs",
        "dynamic-programming",
        "complexity-analysis"
      ],
      "skills": [
        "arrays",
        "linked-lists", 
        "stacks",
        "queues",
        "hash-tables",
        "sorting-algorithms",
        "search-algorithms",
        "tree-traversal",
        "graph-algorithms",
        "dynamic-programming"
      ],
      "learningOutcomes": [
        "Understand fundamental data structures",
        "Implement common algorithms",
        "Analyze time and space complexity",
        "Solve coding problems efficiently"
      ]
    },
    "systems": {
      "id": "systems",
      "name": "Systems Path",
      "icon": "🏗️",
      "description": "Build scalable and distributed systems",
      "difficulty": "intermediate",
      "estimatedWeeks": 8,
      "estimatedHours": 60,
      "prerequisites": ["foundations"],
      "color": "#10b981",
      "tutorials": [
        "system-design-101",
        "distributed-systems",
        "microservices",
        "database-design",
        "caching",
        "load-balancing",
        "message-queues",
        "consensus-algorithms",
        "distributed-storage",
        "system-reliability"
      ],
      "skills": [
        "system-architecture",
        "distributed-systems",
        "microservices",
        "database-design",
        "caching-strategies",
        "load-balancing",
        "message-queues",
        "consensus-algorithms"
      ],
      "learningOutcomes": [
        "Design scalable system architectures",
        "Implement distributed systems patterns",
        "Optimize system performance",
        "Ensure system reliability"
      ]
    }
  },
  "tutorials": {
    "data-structures-algorithms-101": {
      "id": "data-structures-algorithms-101",
      "title": "Data Structures & Algorithms 101",
      "pathId": "foundations",
      "order": 1,
      "difficulty": "beginner",
      "estimatedHours": 4,
      "xpValue": 50,
      "prerequisites": [],
      "skills": ["arrays", "linked-lists", "algorithm-analysis"],
      "description": "Introduction to fundamental data structures and algorithms",
      "longDescription": "This comprehensive tutorial covers the essential data structures and algorithms that form the foundation of computer science. You'll learn about arrays, linked lists, stacks, queues, and basic algorithm analysis techniques.",
      "githubUrl": "https://github.com/quanhua92/the-engineers-playbook/blob/main/tutorials/data-structures-algorithms-101/README.md",
      "tags": ["beginner", "fundamentals", "algorithms", "data-structures"],
      "nextTutorials": ["hashing", "sorting"],
      "relatedTutorials": ["complexity-analysis"],
      "resources": [
        {
          "type": "video",
          "title": "Data Structures Overview",
          "url": "https://youtube.com/watch?v=example"
        },
        {
          "type": "book",
          "title": "Introduction to Algorithms",
          "author": "Cormen, Leiserson, Rivest, Stein"
        }
      ],
      "exercises": [
        {
          "title": "Implement Dynamic Array",
          "difficulty": "easy",
          "description": "Create a dynamic array class with basic operations"
        },
        {
          "title": "Linked List Operations",
          "difficulty": "medium",
          "description": "Implement insertion, deletion, and search in linked lists"
        }
      ]
    },
    "hashing": {
      "id": "hashing",
      "title": "Hashing & Hash Tables",
      "pathId": "foundations",
      "order": 2,
      "difficulty": "beginner",
      "estimatedHours": 3,
      "xpValue": 40,
      "prerequisites": ["data-structures-algorithms-101"],
      "skills": ["hash-tables", "collision-resolution"],
      "description": "Deep dive into hashing techniques and hash table implementations",
      "longDescription": "Learn how hash tables work under the hood, different collision resolution strategies, and when to use hashing for optimal performance.",
      "githubUrl": "https://github.com/quanhua92/the-engineers-playbook/blob/main/tutorials/hashing/README.md",
      "tags": ["hashing", "data-structures", "performance"],
      "nextTutorials": ["sorting"],
      "relatedTutorials": ["data-structures-algorithms-101"],
      "resources": [],
      "exercises": [
        {
          "title": "Hash Table Implementation",
          "difficulty": "medium",
          "description": "Build a hash table with collision resolution"
        }
      ]
    }
  },
  "achievements": {
    "first-tutorial": {
      "id": "first-tutorial",
      "title": "First Steps",
      "description": "Complete your first tutorial",
      "icon": "🎯",
      "rarity": "common",
      "xpReward": 10,
      "category": "progress"
    },
    "path-complete": {
      "id": "path-complete",
      "title": "Path Master",
      "description": "Complete an entire learning path",
      "icon": "🏆",
      "rarity": "rare",
      "xpReward": 100,
      "category": "mastery"
    },
    "speed-learner": {
      "id": "speed-learner",
      "title": "Speed Learner",
      "description": "Complete 3 tutorials in one day",
      "icon": "⚡",
      "rarity": "epic",
      "xpReward": 50,
      "category": "engagement"
    },
    "sage-mode": {
      "id": "sage-mode",
      "title": "Six Paths Sage",
      "description": "Master all six learning paths",
      "icon": "🌟",
      "rarity": "legendary",
      "xpReward": 500,
      "category": "mastery"
    }
  },
  "levels": {
    "code-ninja": {
      "id": "code-ninja",
      "name": "Code Ninja",
      "minXP": 0,
      "maxXP": 499,
      "description": "Just starting your coding journey",
      "color": "#6b7280"
    },
    "data-sage": {
      "id": "data-sage",
      "name": "Data Sage",
      "minXP": 500,
      "maxXP": 1499,
      "description": "Mastering data structures and algorithms",
      "color": "#3b82f6"
    },
    "systems-master": {
      "id": "systems-master",
      "name": "Systems Master",
      "minXP": 1500,
      "maxXP": 2999,
      "description": "Building scalable systems",
      "color": "#10b981"
    },
    "six-paths-sage": {
      "id": "six-paths-sage",
      "name": "Six Paths Sage",
      "minXP": 3000,
      "maxXP": 999999,
      "description": "Master of all six paths",
      "color": "#8b5cf6"
    }
  }
}
```

### 3. profile.json (Template)

**Purpose**: User profile template and default structure

```json
{
  "user": {
    "name": "Your Name",
    "github": "your-github-username",
    "avatar": "https://github.com/your-github-username.png",
    "email": null,
    "bio": "",
    "location": "",
    "website": "",
    "joinDate": "2024-01-20T10:30:00Z",
    "lastActive": "2024-01-20T10:30:00Z",
    "currentLevel": "code-ninja",
    "totalXP": 0,
    "streak": 0,
    "longestStreak": 0
  },
  "progress": {
    "foundations": {
      "completed": 0,
      "total": 8,
      "completedTutorials": [],
      "currentTutorial": null,
      "startDate": null,
      "completionDate": null,
      "xpEarned": 0,
      "timeSpent": 0,
      "lastActivity": null
    },
    "systems": {
      "completed": 0,
      "total": 10,
      "completedTutorials": [],
      "currentTutorial": null,
      "startDate": null,
      "completionDate": null,
      "xpEarned": 0,
      "timeSpent": 0,
      "lastActivity": null
    },
    "algorithms": {
      "completed": 0,
      "total": 8,
      "completedTutorials": [],
      "currentTutorial": null,
      "startDate": null,
      "completionDate": null,
      "xpEarned": 0,
      "timeSpent": 0,
      "lastActivity": null
    },
    "performance": {
      "completed": 0,
      "total": 8,
      "completedTutorials": [],
      "currentTutorial": null,
      "startDate": null,
      "completionDate": null,
      "xpEarned": 0,
      "timeSpent": 0,
      "lastActivity": null
    },
    "specialized": {
      "completed": 0,
      "total": 9,
      "completedTutorials": [],
      "currentTutorial": null,
      "startDate": null,
      "completionDate": null,
      "xpEarned": 0,
      "timeSpent": 0,
      "lastActivity": null
    },
    "distributed": {
      "completed": 0,
      "total": 8,
      "completedTutorials": [],
      "currentTutorial": null,
      "startDate": null,
      "completionDate": null,
      "xpEarned": 0,
      "timeSpent": 0,
      "lastActivity": null
    },
    "operations": {
      "completed": 0,
      "total": 5,
      "completedTutorials": [],
      "currentTutorial": null,
      "startDate": null,
      "completionDate": null,
      "xpEarned": 0,
      "timeSpent": 0,
      "lastActivity": null
    }
  },
  "preferences": {
    "theme": "light",
    "notifications": {
      "achievements": true,
      "reminders": true,
      "social": true,
      "updates": true
    },
    "privacy": {
      "publicProfile": true,
      "showProgress": true,
      "showStats": true
    },
    "learning": {
      "dailyGoal": 1,
      "reminderTime": "18:00",
      "preferredDifficulty": "intermediate"
    },
    "favoriteDevs": [],
    "bookmarks": [],
    "customSettings": {}
  },
  "achievements": [],
  "stats": {
    "totalTutorials": 0,
    "totalPaths": 0,
    "totalHours": 0,
    "averagePerDay": 0,
    "favoriteSkills": [],
    "strongestPath": null,
    "recentActivity": []
  },
  "social": {
    "followers": [],
    "following": [],
    "sharedProgress": [],
    "comparisons": []
  },
  "metadata": {
    "version": "1.0.0",
    "createdAt": "2024-01-20T10:30:00Z",
    "updatedAt": "2024-01-20T10:30:00Z",
    "migratedFrom": null
  }
}
```

### 4. metadata.json

**Purpose**: Application metadata and build information

```json
{
  "build": {
    "version": "1.0.0",
    "buildDate": "2024-01-20T10:30:00Z",
    "commitHash": "abc123def456",
    "environment": "production",
    "bundleSize": "485KB",
    "dependencies": {
      "react": "^18.2.0",
      "@tanstack/react-router": "^1.0.0",
      "tailwindcss": "^3.3.0"
    }
  },
  "content": {
    "lastSyncDate": "2024-01-20T10:30:00Z",
    "totalTutorials": 56,
    "totalPaths": 6,
    "contentVersion": "1.0.0",
    "checksum": "sha256:abc123..."
  },
  "performance": {
    "averageLoadTime": "1.2s",
    "bundleOptimized": true,
    "cacheEnabled": true,
    "compressionEnabled": true
  },
  "features": {
    "experimental": [],
    "deprecated": [],
    "comingSoon": ["mobile-app", "offline-sync"]
  }
}
```

## 🔧 TypeScript Interfaces

### Core Types

```typescript
// types/config.ts
export interface Config {
  app: {
    name: string;
    version: string;
    description: string;
    author: string;
    license: string;
    repository: string;
  };
  sourceRepo: {
    owner: string;
    repo: string;
    branch: string;
    tutorialsPath: string;
  };
  links: {
    tutorialsRepo: string;
    documentation: string;
    community: string;
    support: string;
  };
  features: {
    enablePeerComparison: boolean;
    enableExport: boolean;
    enableSync: boolean;
    enableLeaderboard: boolean;
    enableOfflineMode: boolean;
    enableNotifications: boolean;
  };
  ui: {
    theme: 'light' | 'dark';
    primaryColor: string;
    accentColor: string;
    darkMode: boolean;
    animations: boolean;
  };
  performance: {
    enableLazyLoading: boolean;
    enableImageOptimization: boolean;
    enableBundleSplitting: boolean;
    maxCacheSize: number;
  };
  analytics: {
    enabled: boolean;
    provider: string;
    trackingId: string | null;
  };
}

// types/data.ts
export interface DataSchema {
  lastUpdated: string;
  version: string;
  metadata: {
    totalTutorials: number;
    totalPaths: number;
    estimatedHours: number;
    difficultyLevels: string[];
    skills: string[];
  };
  paths: Record<string, Path>;
  tutorials: Record<string, Tutorial>;
  achievements: Record<string, AchievementDefinition>;
  levels: Record<string, Level>;
}

export interface Path {
  id: string;
  name: string;
  icon: string;
  description: string;
  difficulty: 'beginner' | 'intermediate' | 'advanced';
  estimatedWeeks: number;
  estimatedHours: number;
  prerequisites: string[];
  color: string;
  tutorials: string[];
  skills: string[];
  learningOutcomes: string[];
}

export interface Tutorial {
  id: string;
  title: string;
  pathId: string;
  order: number;
  difficulty: 'beginner' | 'intermediate' | 'advanced';
  estimatedHours: number;
  xpValue: number;
  prerequisites: string[];
  skills: string[];
  description: string;
  longDescription: string;
  githubUrl: string;
  tags: string[];
  nextTutorials: string[];
  relatedTutorials: string[];
  resources: Resource[];
  exercises: Exercise[];
}

export interface Resource {
  type: 'video' | 'book' | 'article' | 'course';
  title: string;
  url?: string;
  author?: string;
  description?: string;
}

export interface Exercise {
  title: string;
  difficulty: 'easy' | 'medium' | 'hard';
  description: string;
  solution?: string;
}

export interface AchievementDefinition {
  id: string;
  title: string;
  description: string;
  icon: string;
  rarity: 'common' | 'rare' | 'epic' | 'legendary';
  xpReward: number;
  category: 'progress' | 'mastery' | 'engagement' | 'social';
}

export interface Level {
  id: string;
  name: string;
  minXP: number;
  maxXP: number;
  description: string;
  color: string;
}
```

### User Profile Types

```typescript
// types/profile.ts
export interface UserProfile {
  user: UserInfo;
  progress: Record<string, PathProgress>;
  preferences: UserPreferences;
  achievements: Achievement[];
  stats: UserStats;
  social: SocialData;
  metadata: ProfileMetadata;
}

export interface UserInfo {
  name: string;
  github: string;
  avatar: string;
  email: string | null;
  bio: string;
  location: string;
  website: string;
  joinDate: string;
  lastActive: string;
  currentLevel: string;
  totalXP: number;
  streak: number;
  longestStreak: number;
}

export interface PathProgress {
  completed: number;
  total: number;
  completedTutorials: string[];
  currentTutorial: string | null;
  startDate: string | null;
  completionDate: string | null;
  xpEarned: number;
  timeSpent: number;
  lastActivity: string | null;
}

export interface UserPreferences {
  theme: 'light' | 'dark';
  notifications: {
    achievements: boolean;
    reminders: boolean;
    social: boolean;
    updates: boolean;
  };
  privacy: {
    publicProfile: boolean;
    showProgress: boolean;
    showStats: boolean;
  };
  learning: {
    dailyGoal: number;
    reminderTime: string;
    preferredDifficulty: 'beginner' | 'intermediate' | 'advanced';
  };
  favoriteDevs: string[];
  bookmarks: string[];
  customSettings: Record<string, any>;
}

export interface Achievement {
  id: string;
  title: string;
  description: string;
  icon: string;
  rarity: 'common' | 'rare' | 'epic' | 'legendary';
  unlockedAt: string;
  path?: string;
  xpReward: number;
}

export interface UserStats {
  totalTutorials: number;
  totalPaths: number;
  totalHours: number;
  averagePerDay: number;
  favoriteSkills: string[];
  strongestPath: string | null;
  recentActivity: ActivityRecord[];
}

export interface SocialData {
  followers: string[];
  following: string[];
  sharedProgress: SharedProgress[];
  comparisons: ProgressComparison[];
}

export interface ActivityRecord {
  type: 'tutorial_completed' | 'path_completed' | 'achievement_unlocked';
  timestamp: string;
  data: Record<string, any>;
}

export interface SharedProgress {
  platform: 'twitter' | 'linkedin' | 'github';
  timestamp: string;
  content: string;
}

export interface ProgressComparison {
  username: string;
  comparedAt: string;
  results: ComparisonResult[];
}

export interface ComparisonResult {
  pathId: string;
  myProgress: number;
  peerProgress: number;
  difference: number;
}

export interface ProfileMetadata {
  version: string;
  createdAt: string;
  updatedAt: string;
  migratedFrom: string | null;
}
```

### External Profile Types

```typescript
// types/external.ts
export interface ExternalProfile {
  username: string;
  repoUrl: string;
  siteUrl: string;
  profile: UserProfile;
  lastFetched: string;
  isValid: boolean;
  error?: string;
}

export interface GitHubProfile {
  username: string;
  displayName: string;
  avatar: string;
  bio: string;
  location: string;
  company: string;
  blog: string;
  publicRepos: number;
  followers: number;
  following: number;
  joinDate: string;
}

export interface RankingSubmission {
  username: string;
  displayName: string;
  repoUrl: string;
  siteUrl: string;
  lastUpdated: string;
  stats: {
    totalXP: number;
    completedPaths: number;
    totalTutorials: number;
    currentLevel: string;
    achievements: number;
    streak: number;
  };
  pathProgress: Record<string, {
    completed: number;
    total: number;
  }>;
}
```

## 🛠️ Utility Types

```typescript
// types/utils.ts
export type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};

export type RequiredFields<T, K extends keyof T> = T & Required<Pick<T, K>>;

export type OptionalFields<T, K extends keyof T> = Omit<T, K> & Partial<Pick<T, K>>;

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  timestamp: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
  hasMore: boolean;
}

export interface SearchFilters {
  difficulty?: string[];
  skills?: string[];
  paths?: string[];
  completed?: boolean;
  estimatedHours?: {
    min?: number;
    max?: number;
  };
}

export interface SortOptions {
  field: string;
  direction: 'asc' | 'desc';
}
```

## 🔍 Data Validation

```typescript
// lib/validation.ts
import { z } from 'zod';

export const ConfigSchema = z.object({
  app: z.object({
    name: z.string(),
    version: z.string(),
    description: z.string(),
    author: z.string(),
    license: z.string(),
    repository: z.string().url()
  }),
  sourceRepo: z.object({
    owner: z.string(),
    repo: z.string(),
    branch: z.string(),
    tutorialsPath: z.string()
  }),
  features: z.object({
    enablePeerComparison: z.boolean(),
    enableExport: z.boolean(),
    enableSync: z.boolean(),
    enableLeaderboard: z.boolean()
  })
});

export const TutorialSchema = z.object({
  id: z.string(),
  title: z.string(),
  pathId: z.string(),
  difficulty: z.enum(['beginner', 'intermediate', 'advanced']),
  estimatedHours: z.number().positive(),
  xpValue: z.number().positive(),
  prerequisites: z.array(z.string()),
  skills: z.array(z.string()),
  description: z.string(),
  githubUrl: z.string().url()
});

export const UserProfileSchema = z.object({
  user: z.object({
    name: z.string().min(1),
    github: z.string().min(1),
    avatar: z.string().url(),
    totalXP: z.number().nonnegative(),
    currentLevel: z.string()
  }),
  progress: z.record(z.object({
    completed: z.number().nonnegative(),
    total: z.number().positive(),
    completedTutorials: z.array(z.string()),
    xpEarned: z.number().nonnegative()
  }))
});

// Validation functions
export function validateConfig(data: unknown): Config {
  return ConfigSchema.parse(data);
}

export function validateTutorial(data: unknown): Tutorial {
  return TutorialSchema.parse(data);
}

export function validateUserProfile(data: unknown): UserProfile {
  return UserProfileSchema.parse(data);
}
```

## 📦 Data Access Layer

```typescript
// lib/data-access.ts
export class DataAccessLayer {
  private static instance: DataAccessLayer;
  private cache: Map<string, any> = new Map();

  static getInstance(): DataAccessLayer {
    if (!DataAccessLayer.instance) {
      DataAccessLayer.instance = new DataAccessLayer();
    }
    return DataAccessLayer.instance;
  }

  async loadConfig(): Promise<Config> {
    if (this.cache.has('config')) {
      return this.cache.get('config');
    }

    const response = await fetch('/data/config.json');
    const data = await response.json();
    const config = validateConfig(data);
    
    this.cache.set('config', config);
    return config;
  }

  async loadData(): Promise<DataSchema> {
    if (this.cache.has('data')) {
      return this.cache.get('data');
    }

    const response = await fetch('/data/data.json');
    const data = await response.json();
    
    this.cache.set('data', data);
    return data;
  }

  async saveProfile(profile: UserProfile): Promise<void> {
    const validatedProfile = validateUserProfile(profile);
    localStorage.setItem('codesagemode-profile', JSON.stringify(validatedProfile));
    this.cache.set('profile', validatedProfile);
  }

  async loadProfile(): Promise<UserProfile | null> {
    const stored = localStorage.getItem('codesagemode-profile');
    if (!stored) return null;

    try {
      const profile = JSON.parse(stored);
      return validateUserProfile(profile);
    } catch {
      return null;
    }
  }

  clearCache(): void {
    this.cache.clear();
  }
}
```

## 🔄 Migration Support

```typescript
// lib/migrations.ts
export interface Migration {
  version: string;
  description: string;
  up: (data: any) => any;
  down: (data: any) => any;
}

export const migrations: Migration[] = [
  {
    version: '1.0.0',
    description: 'Initial schema',
    up: (data) => data,
    down: (data) => data
  },
  {
    version: '1.1.0',
    description: 'Add social features',
    up: (data) => ({
      ...data,
      social: {
        followers: [],
        following: [],
        sharedProgress: [],
        comparisons: []
      }
    }),
    down: (data) => {
      const { social, ...rest } = data;
      return rest;
    }
  }
];

export function migrateData(data: any, targetVersion: string): any {
  // Implementation for data migration
  return data;
}
```

---

**This comprehensive data schema ensures type safety, consistency, and scalability across the entire SixPathsAcademy application.** 🚀

*All data structures are designed to be extensible and backward-compatible for future enhancements.*