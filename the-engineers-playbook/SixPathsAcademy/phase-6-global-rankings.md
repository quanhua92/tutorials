# Phase 6: Global Rankings (Weeks 11-12)

> **Implement Git-based global rankings system with individual file ownership and automatic aggregation**

## 🎯 Phase Goals

- Create Git-based global rankings system with zero infrastructure costs
- Implement individual user file ownership to avoid conflicts
- Build automatic aggregation system using GitHub Actions
- Develop client-side integration for rankings display and submission
- Create community-driven leaderboard with transparent participation

## 📋 Tasks Breakdown

### **Week 11: Git-Based Rankings Infrastructure**

#### Task 6.1: Main Repository Structure Setup
**Estimated Time: 4 hours**

**Create in `quanhua92/SixPathsAcademy` repository:**
```
global/
├── rankings.json                    # Auto-generated aggregated data
├── users/                          # Individual user files
│   ├── alice92.json               # Example user submission
│   ├── bob-coder.json
│   └── jane-dev.json
├── scripts/
│   ├── generate-rankings.js       # Aggregation script
│   ├── validate-submission.js     # Validation utilities
│   └── utils.js                   # Helper functions
├── schemas/
│   └── user-submission.schema.json # JSON schema for validation
└── README.md                      # Submission guidelines
```

**User Submission Schema:**
```json
// global/schemas/user-submission.schema.json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["username", "displayName", "repoUrl", "siteUrl", "lastUpdated", "stats", "pathProgress"],
  "properties": {
    "username": {
      "type": "string",
      "pattern": "^[a-zA-Z0-9_-]+$",
      "minLength": 1,
      "maxLength": 50
    },
    "displayName": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "repoUrl": {
      "type": "string",
      "format": "uri",
      "pattern": "^https://github.com/"
    },
    "siteUrl": {
      "type": "string",
      "format": "uri"
    },
    "lastUpdated": {
      "type": "string",
      "format": "date-time"
    },
    "stats": {
      "type": "object",
      "required": ["totalXP", "completedPaths", "totalTutorials", "currentLevel", "achievements", "streak"],
      "properties": {
        "totalXP": { "type": "number", "minimum": 0 },
        "completedPaths": { "type": "number", "minimum": 0, "maximum": 6 },
        "totalTutorials": { "type": "number", "minimum": 0 },
        "currentLevel": { "type": "string" },
        "achievements": { "type": "number", "minimum": 0 },
        "streak": { "type": "number", "minimum": 0 }
      }
    },
    "pathProgress": {
      "type": "object",
      "properties": {
        "foundations": { "$ref": "#/definitions/pathProgress" },
        "systems": { "$ref": "#/definitions/pathProgress" },
        "algorithms": { "$ref": "#/definitions/pathProgress" },
        "performance": { "$ref": "#/definitions/pathProgress" },
        "specialized": { "$ref": "#/definitions/pathProgress" },
        "distributed": { "$ref": "#/definitions/pathProgress" },
        "operations": { "$ref": "#/definitions/pathProgress" }
      }
    }
  },
  "definitions": {
    "pathProgress": {
      "type": "object",
      "required": ["completed", "total"],
      "properties": {
        "completed": { "type": "number", "minimum": 0 },
        "total": { "type": "number", "minimum": 0 }
      }
    }
  }
}
```

#### Task 6.2: Aggregation Script Development
**Estimated Time: 8 hours**

```javascript
// global/scripts/generate-rankings.js
const fs = require('fs');
const path = require('path');
const Ajv = require('ajv');
const addFormats = require('ajv-formats');

const ajv = new Ajv();
addFormats(ajv);

// Load schema
const schema = JSON.parse(fs.readFileSync(path.join(__dirname, '../schemas/user-submission.schema.json'), 'utf8'));
const validate = ajv.compile(schema);

function generateRankings() {
  const usersDir = path.join(__dirname, '../users');
  const users = [];
  const errors = [];

  // Read all user files
  const userFiles = fs.readdirSync(usersDir).filter(file => file.endsWith('.json'));
  
  for (const file of userFiles) {
    try {
      const userData = JSON.parse(fs.readFileSync(path.join(usersDir, file), 'utf8'));
      
      // Validate against schema
      if (!validate(userData)) {
        errors.push({
          file,
          errors: validate.errors
        });
        continue;
      }
      
      // Additional validation
      if (file !== `${userData.username}.json`) {
        errors.push({
          file,
          errors: [`Filename must match username: expected ${userData.username}.json`]
        });
        continue;
      }
      
      users.push(userData);
    } catch (error) {
      errors.push({
        file,
        errors: [error.message]
      });
    }
  }

  // Generate rankings
  const rankings = {
    generatedAt: new Date().toISOString(),
    totalUsers: users.length,
    validationErrors: errors,
    
    // Global leaderboard
    global: users
      .sort((a, b) => b.stats.totalXP - a.stats.totalXP)
      .slice(0, 100)
      .map((user, index) => ({
        rank: index + 1,
        username: user.username,
        displayName: user.displayName,
        siteUrl: user.siteUrl,
        totalXP: user.stats.totalXP,
        completedPaths: user.stats.completedPaths,
        totalTutorials: user.stats.totalTutorials,
        currentLevel: user.stats.currentLevel,
        achievements: user.stats.achievements,
        streak: user.stats.streak,
        lastUpdated: user.lastUpdated
      })),
    
    // Path-specific leaderboards
    paths: {
      foundations: generatePathLeaderboard(users, 'foundations'),
      systems: generatePathLeaderboard(users, 'systems'),
      algorithms: generatePathLeaderboard(users, 'algorithms'),
      performance: generatePathLeaderboard(users, 'performance'),
      specialized: generatePathLeaderboard(users, 'specialized'),
      distributed: generatePathLeaderboard(users, 'distributed'),
      operations: generatePathLeaderboard(users, 'operations')
    },
    
    // Statistics
    stats: {
      averageXP: Math.round(users.reduce((sum, u) => sum + u.stats.totalXP, 0) / users.length),
      averageCompletedPaths: Math.round(users.reduce((sum, u) => sum + u.stats.completedPaths, 0) / users.length * 10) / 10,
      averageStreak: Math.round(users.reduce((sum, u) => sum + u.stats.streak, 0) / users.length),
      totalTutorialsCompleted: users.reduce((sum, u) => sum + u.stats.totalTutorials, 0),
      sageCount: users.filter(u => u.stats.completedPaths === 6).length,
      levelDistribution: getLevelDistribution(users)
    }
  };

  // Write rankings file
  fs.writeFileSync(
    path.join(__dirname, '../rankings.json'),
    JSON.stringify(rankings, null, 2)
  );

  console.log(`✅ Rankings generated successfully!`);
  console.log(`📊 Total users: ${rankings.totalUsers}`);
  console.log(`🏆 Six Paths Sages: ${rankings.stats.sageCount}`);
  console.log(`⚠️  Validation errors: ${errors.length}`);
  
  if (errors.length > 0) {
    console.log('\nValidation errors:');
    errors.forEach(error => {
      console.log(`❌ ${error.file}: ${error.errors.join(', ')}`);
    });
  }
}

function generatePathLeaderboard(users, pathId) {
  return users
    .filter(user => user.pathProgress[pathId])
    .sort((a, b) => {
      const aProgress = a.pathProgress[pathId];
      const bProgress = b.pathProgress[pathId];
      
      // Sort by completion percentage, then by completion date
      const aPercentage = aProgress.completed / aProgress.total;
      const bPercentage = bProgress.completed / bProgress.total;
      
      if (aPercentage !== bPercentage) {
        return bPercentage - aPercentage;
      }
      
      // If same percentage, sort by XP (assuming higher XP = faster completion)
      return b.stats.totalXP - a.stats.totalXP;
    })
    .slice(0, 50)
    .map((user, index) => ({
      rank: index + 1,
      username: user.username,
      displayName: user.displayName,
      siteUrl: user.siteUrl,
      completed: user.pathProgress[pathId].completed,
      total: user.pathProgress[pathId].total,
      percentage: Math.round((user.pathProgress[pathId].completed / user.pathProgress[pathId].total) * 100),
      lastUpdated: user.lastUpdated
    }));
}

function getLevelDistribution(users) {
  const distribution = {};
  users.forEach(user => {
    distribution[user.stats.currentLevel] = (distribution[user.stats.currentLevel] || 0) + 1;
  });
  return distribution;
}

// Run the script
generateRankings();
```

#### Task 6.3: GitHub Actions Workflow
**Estimated Time: 4 hours**

```yaml
# .github/workflows/update-rankings.yml
name: Update Global Rankings

on:
  push:
    paths: ['global/users/**']
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:  # Allow manual triggering

jobs:
  update-rankings:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '18'
          cache: 'npm'
          cache-dependency-path: 'global/package.json'
      
      - name: Install dependencies
        run: |
          cd global
          npm ci
      
      - name: Generate rankings
        run: |
          cd global
          node scripts/generate-rankings.js
      
      - name: Check for changes
        id: changes
        run: |
          if git diff --quiet global/rankings.json; then
            echo "changed=false" >> $GITHUB_OUTPUT
          else
            echo "changed=true" >> $GITHUB_OUTPUT
          fi
      
      - name: Commit updated rankings
        if: steps.changes.outputs.changed == 'true'
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add global/rankings.json
          git commit -m "🏆 Auto-update global rankings [$(date +'%Y-%m-%d %H:%M:%S')]"
          git push
      
      - name: Create summary
        if: steps.changes.outputs.changed == 'true'
        run: |
          echo "## 🏆 Rankings Updated" >> $GITHUB_STEP_SUMMARY
          echo "Rankings have been automatically updated based on user submissions." >> $GITHUB_STEP_SUMMARY
          echo "Check the updated [rankings.json](https://github.com/quanhua92/SixPathsAcademy/blob/main/global/rankings.json)" >> $GITHUB_STEP_SUMMARY
```

**Package.json for scripts:**
```json
// global/package.json
{
  "name": "codesagemode-global",
  "version": "1.0.0",
  "description": "Global rankings system for SixPathsAcademy",
  "scripts": {
    "generate": "node scripts/generate-rankings.js",
    "validate": "node scripts/validate-submission.js",
    "test": "jest"
  },
  "dependencies": {
    "ajv": "^8.12.0",
    "ajv-formats": "^2.1.1"
  },
  "devDependencies": {
    "jest": "^29.7.0"
  }
}
```

### **Week 12: Client Integration & User Experience**

#### Task 6.4: Global Rankings Display
**Estimated Time: 10 hours**

```typescript
// routes/leaderboard.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/leaderboard',
  component: LeaderboardPage,
  loader: async () => {
    const rankings = await fetchGlobalRankings();
    return { rankings };
  },
});

async function fetchGlobalRankings() {
  try {
    const response = await fetch('https://raw.githubusercontent.com/quanhua92/SixPathsAcademy/main/global/rankings.json');
    return await response.json();
  } catch (error) {
    console.error('Failed to fetch global rankings:', error);
    return null;
  }
}

function LeaderboardPage() {
  const { rankings } = Route.useLoaderData();
  const [selectedPath, setSelectedPath] = useState<string>('global');
  const { profile } = useProfile();
  
  if (!rankings) {
    return (
      <div className="text-center py-12">
        <div className="text-muted-foreground">
          Unable to load global rankings. Please try again later.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="text-center space-y-4">
        <h1 className="text-4xl font-bold gradient-text">
          🏆 Global Leaderboard
        </h1>
        <p className="text-muted-foreground max-w-2xl mx-auto">
          See how you stack up against the SixPathsAcademy community. Rankings are updated every 6 hours.
        </p>
        
        <div className="flex justify-center items-center space-x-4 text-sm">
          <Badge variant="outline">
            👥 {rankings.totalUsers} Active Users
          </Badge>
          <Badge variant="outline">
            🌟 {rankings.stats.sageCount} Six Paths Sages
          </Badge>
          <Badge variant="outline">
            📚 {rankings.stats.totalTutorialsCompleted} Total Completions
          </Badge>
        </div>
      </div>

      {/* My Ranking */}
      {profile && (
        <MyRankingCard profile={profile} rankings={rankings} />
      )}

      {/* Path Selector */}
      <div className="flex justify-center">
        <Tabs value={selectedPath} onValueChange={setSelectedPath}>
          <TabsList className="grid w-full grid-cols-8">
            <TabsTrigger value="global">🏆 Global</TabsTrigger>
            <TabsTrigger value="foundations">📚 Foundations</TabsTrigger>
            <TabsTrigger value="systems">🏗️ Systems</TabsTrigger>
            <TabsTrigger value="algorithms">🧠 Algorithms</TabsTrigger>
            <TabsTrigger value="performance">⚡ Performance</TabsTrigger>
            <TabsTrigger value="specialized">🔬 Specialized</TabsTrigger>
            <TabsTrigger value="distributed">🌐 Distributed</TabsTrigger>
            <TabsTrigger value="operations">🛠️ Operations</TabsTrigger>
          </TabsList>
          
          <TabsContent value="global" className="mt-6">
            <GlobalLeaderboard rankings={rankings.global} />
          </TabsContent>
          
          {Object.entries(rankings.paths).map(([pathId, pathRankings]) => (
            <TabsContent key={pathId} value={pathId} className="mt-6">
              <PathLeaderboard pathId={pathId} rankings={pathRankings} />
            </TabsContent>
          ))}
        </Tabs>
      </div>

      {/* Community Stats */}
      <CommunityStats stats={rankings.stats} />
      
      {/* Join Rankings CTA */}
      <JoinRankingsCTA />
      
      {/* Last Updated */}
      <div className="text-center text-sm text-muted-foreground">
        Last updated: {new Date(rankings.generatedAt).toLocaleString()}
      </div>
    </div>
  );
}

// components/features/GlobalLeaderboard.tsx
function GlobalLeaderboard({ rankings }: { rankings: any[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>🏆 Global Rankings</CardTitle>
        <CardDescription>Top SixPathsAcademy learners ranked by total XP</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {rankings.map((user, index) => (
            <div
              key={user.username}
              className="flex items-center justify-between p-3 rounded-lg hover:bg-muted/50 transition-colors"
            >
              <div className="flex items-center space-x-4">
                <div className="text-2xl font-bold text-muted-foreground min-w-[3rem]">
                  {getRankEmoji(user.rank)}{user.rank}
                </div>
                <div>
                  <div className="font-semibold">{user.displayName}</div>
                  <div className="text-sm text-muted-foreground">
                    @{user.username}
                  </div>
                </div>
              </div>
              
              <div className="flex items-center space-x-6">
                <div className="text-right">
                  <div className="font-bold text-lg">{user.totalXP.toLocaleString()}</div>
                  <div className="text-sm text-muted-foreground">XP</div>
                </div>
                
                <div className="text-right">
                  <div className="font-semibold">{user.completedPaths}/6</div>
                  <div className="text-sm text-muted-foreground">Paths</div>
                </div>
                
                <div className="text-right">
                  <div className="font-semibold">{user.streak}</div>
                  <div className="text-sm text-muted-foreground">Streak</div>
                </div>
                
                <Button
                  variant="outline"
                  size="sm"
                  asChild
                >
                  <a href={user.siteUrl} target="_blank" rel="noopener noreferrer">
                    View Profile
                  </a>
                </Button>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
```

#### Task 6.5: User Submission Flow
**Estimated Time: 8 hours**

```typescript
// components/features/JoinRankingsCTA.tsx
function JoinRankingsCTA() {
  const { profile } = useProfile();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionData, setSubmissionData] = useState<string>('');
  
  const generateSubmission = () => {
    if (!profile) return;
    
    const submission = {
      username: profile.user.github,
      displayName: profile.user.name,
      repoUrl: `https://github.com/${profile.user.github}/my-codesagemode-progress`,
      siteUrl: `https://${profile.user.github}-codesagemode.vercel.app`,
      lastUpdated: new Date().toISOString(),
      stats: {
        totalXP: profile.user.totalXP,
        completedPaths: Object.values(profile.progress).filter(p => p.completed === p.total).length,
        totalTutorials: Object.values(profile.progress).reduce((sum, p) => sum + p.completed, 0),
        currentLevel: profile.user.currentLevel,
        achievements: profile.achievements.length,
        streak: calculateStreak(profile) // Implementation needed
      },
      pathProgress: {
        foundations: {
          completed: profile.progress.foundations?.completed || 0,
          total: profile.progress.foundations?.total || 8
        },
        systems: {
          completed: profile.progress.systems?.completed || 0,
          total: profile.progress.systems?.total || 10
        },
        algorithms: {
          completed: profile.progress.algorithms?.completed || 0,
          total: profile.progress.algorithms?.total || 8
        },
        performance: {
          completed: profile.progress.performance?.completed || 0,
          total: profile.progress.performance?.total || 8
        },
        specialized: {
          completed: profile.progress.specialized?.completed || 0,
          total: profile.progress.specialized?.total || 9
        },
        distributed: {
          completed: profile.progress.distributed?.completed || 0,
          total: profile.progress.distributed?.total || 8
        },
        operations: {
          completed: profile.progress.operations?.completed || 0,
          total: profile.progress.operations?.total || 5
        }
      }
    };
    
    setSubmissionData(JSON.stringify(submission, null, 2));
  };
  
  const handleSubmit = async () => {
    setIsSubmitting(true);
    
    // Copy to clipboard
    await navigator.clipboard.writeText(submissionData);
    
    // Open GitHub to create new file
    const githubUrl = `https://github.com/quanhua92/SixPathsAcademy/new/main/global/users?filename=${profile?.user.github}.json&value=${encodeURIComponent(submissionData)}`;
    window.open(githubUrl, '_blank');
    
    setIsSubmitting(false);
  };

  return (
    <Card className="border-dashed border-2 border-muted">
      <CardHeader>
        <CardTitle className="text-center">🚀 Join the Global Rankings</CardTitle>
        <CardDescription className="text-center">
          Share your SixPathsAcademy progress with the community!
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="text-center space-y-2">
          <p className="text-sm text-muted-foreground">
            Ready to showcase your learning journey? Generate your submission and join the global leaderboard.
          </p>
          
          <div className="flex justify-center space-x-4">
            <Button onClick={generateSubmission} disabled={!profile}>
              📊 Generate Submission
            </Button>
            
            {submissionData && (
              <Button onClick={handleSubmit} disabled={isSubmitting}>
                {isSubmitting ? 'Submitting...' : '🚀 Submit to Rankings'}
              </Button>
            )}
          </div>
        </div>
        
        {submissionData && (
          <div className="space-y-2">
            <div className="text-sm font-semibold">Your submission data:</div>
            <pre className="text-xs bg-muted p-3 rounded-md overflow-x-auto max-h-64">
              {submissionData}
            </pre>
            
            <div className="text-sm text-muted-foreground">
              <strong>Next steps:</strong>
              <ol className="list-decimal list-inside mt-2 space-y-1">
                <li>Click "Submit to Rankings" to open GitHub</li>
                <li>Review your submission data</li>
                <li>Create a Pull Request to join the rankings</li>
                <li>Update your file anytime to refresh your ranking</li>
              </ol>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

## 📋 Documentation Tasks

#### Task 6.6: User Documentation
**Estimated Time: 4 hours**

```markdown
# global/README.md
# SixPathsAcademy Global Rankings

Welcome to the SixPathsAcademy global rankings system! This community-driven leaderboard showcases the progress of developers mastering the Six Paths of Software Engineering.

## 🏆 How It Works

1. **Individual Ownership**: Each user maintains their own JSON file in `global/users/`
2. **Self-Service Updates**: Update your file anytime to refresh your ranking
3. **Automatic Aggregation**: GitHub Actions regenerates rankings every 6 hours
4. **Zero Conflicts**: No database, no conflicts - just Git-based simplicity

## 🚀 Joining the Rankings

### Step 1: Generate Your Submission
Visit your SixPathsAcademy site and use the "Join Rankings" feature to generate your submission data.

### Step 2: Create Your User File
1. Fork this repository
2. Create a new file: `global/users/your-username.json`
3. Copy your generated submission data
4. Create a Pull Request

### Step 3: Maintain Your Progress
- Update ONLY your own file: `global/users/your-username.json`
- Commit directly to main branch (no PR needed for updates)
- Rankings will automatically update within 6 hours

## 📊 File Format

Your user file should follow this structure:

```json
{
  "username": "your-github-username",
  "displayName": "Your Display Name",
  "repoUrl": "https://github.com/your-username/your-codesagemode-repo",
  "siteUrl": "https://your-codesagemode-site.vercel.app",
  "lastUpdated": "2024-01-20T10:30:00Z",
  "stats": {
    "totalXP": 2450,
    "completedPaths": 4,
    "totalTutorials": 32,
    "currentLevel": "Systems Master",
    "achievements": 12,
    "streak": 15
  },
  "pathProgress": {
    "foundations": { "completed": 8, "total": 8 },
    "systems": { "completed": 10, "total": 10 },
    "algorithms": { "completed": 6, "total": 8 },
    "performance": { "completed": 4, "total": 8 },
    "specialized": { "completed": 2, "total": 9 },
    "distributed": { "completed": 1, "total": 8 },
    "operations": { "completed": 1, "total": 5 }
  }
}
```

## 🎯 Six Paths Progress

Track your mastery across all six learning paths:

- **📚 Foundations** (8 tutorials) - Core concepts and data structures
- **🏗️ Systems** (10 tutorials) - Distributed systems and architecture
- **🧠 Algorithms** (8 tutorials) - Advanced algorithms and problem-solving
- **⚡ Performance** (8 tutorials) - Optimization and efficiency techniques
- **🔬 Specialized** (9 tutorials) - Advanced specialized data structures
- **🌐 Distributed** (8 tutorials) - Advanced distributed patterns
- **🛠️ Operations** (5 tutorials) - Production systems and reliability

## 🤝 Community Guidelines

- **Be Honest**: Only mark tutorials as complete when you've genuinely learned them
- **Be Respectful**: This is a learning community, not a competition
- **Be Helpful**: Share your learning journey and help others
- **Own Your File**: Only edit your own user file to avoid conflicts

## 🔧 Technical Details

- **Validation**: All submissions are validated against a JSON schema
- **Aggregation**: Rankings are regenerated automatically via GitHub Actions
- **Transparency**: All data is public and auditable through Git history
- **Performance**: Efficient Git-based system with zero infrastructure costs

## 🌟 Recognition Levels

- **🥉 Code Apprentice**: 1-2 paths completed
- **🥈 Data Sage**: 3-4 paths completed  
- **🥇 Systems Master**: 5 paths completed
- **🏆 Six Paths Sage**: All 6 paths mastered

## 📈 Statistics

Current community stats are automatically generated and displayed in the global rankings:
- Total active users
- Average XP and completion rates
- Six Paths Sage count
- Learning streaks and achievements

## 🚀 Get Started

Ready to join the global SixPathsAcademy community? Start by setting up your personal SixPathsAcademy site and begin your journey through the Six Paths of Software Engineering!

[Get Started with SixPathsAcademy](https://github.com/quanhua92/SixPathsAcademy)
```

## 🧪 Testing Tasks

#### Task 6.7: Ranking System Tests
**Estimated Time: 4 hours**

```javascript
// global/scripts/generate-rankings.test.js
const { generateRankings } = require('./generate-rankings');

describe('Rankings Generation', () => {
  test('should generate valid rankings from user data', () => {
    // Test with mock user data
    const mockUsers = [
      {
        username: 'alice',
        stats: { totalXP: 2000, completedPaths: 3 },
        pathProgress: { foundations: { completed: 8, total: 8 } }
      },
      {
        username: 'bob',
        stats: { totalXP: 1500, completedPaths: 2 },
        pathProgress: { foundations: { completed: 6, total: 8 } }
      }
    ];
    
    const rankings = generateRankings(mockUsers);
    
    expect(rankings.global[0].username).toBe('alice');
    expect(rankings.global[0].rank).toBe(1);
    expect(rankings.totalUsers).toBe(2);
  });
  
  test('should handle malformed user data gracefully', () => {
    // Test error handling
  });
});
```

## ✅ Definition of Done

- [ ] GitHub repository structure created with proper folders
- [ ] JSON schema validation for user submissions implemented
- [ ] Aggregation script generates rankings correctly
- [ ] GitHub Actions workflow automatically updates rankings
- [ ] Client-side leaderboard displays rankings beautifully
- [ ] User submission flow works smoothly
- [ ] Documentation provides clear instructions
- [ ] Testing covers core functionality
- [ ] Validation handles edge cases and errors
- [ ] Performance is optimized for large user bases

## 🎯 Success Metrics

- **Participation**: Number of users joining global rankings
- **Engagement**: Frequency of user submission updates
- **Community Growth**: Rate of new user onboarding
- **System Reliability**: Uptime of ranking generation
- **User Satisfaction**: Ease of submission and update process

## 🔗 Integration with Other Phases

- **Phase 1-2**: Profile data generation for submissions
- **Phase 3**: Social features can link to global rankings
- **Phase 4**: Export functionality can prepare submission data
- **Phase 5**: Polished UI for leaderboard display

---

**Phase 6 creates a scalable, cost-effective global rankings system that builds community while maintaining the decentralized philosophy of SixPathsAcademy.** 🚀

*The power of Git + GitHub Actions + Community = Infinite scalability at zero cost!*