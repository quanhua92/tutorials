# Phase 3: Social Features (Weeks 5-6)

> **Build peer comparison system and social features to create a community-driven learning experience**

## 🎯 Phase Goals

- Implement peer comparison system with GitHub repository crawling
- Create favorites system for following other developers
- Build social dashboard with progress comparisons
- Develop GitHub API integration for external profile fetching
- Add social sharing features and community engagement tools

## 📋 Tasks Breakdown

### **Week 5: GitHub Repository Crawling & Peer Discovery**

#### Task 3.1: GitHub API Integration
**Estimated Time: 8 hours**

```typescript
// lib/github-api.ts
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

export interface ExternalProfile {
  username: string;
  repoUrl: string;
  siteUrl: string;
  profile: UserProfile;
  lastFetched: string;
  isValid: boolean;
  error?: string;
}

class GitHubService {
  private readonly baseUrl = 'https://api.github.com';
  private readonly rawUrl = 'https://raw.githubusercontent.com';
  
  async fetchUserProfile(username: string): Promise<GitHubProfile | null> {
    try {
      const response = await fetch(`${this.baseUrl}/users/${username}`);
      if (!response.ok) return null;
      
      const data = await response.json();
      return {
        username: data.login,
        displayName: data.name || data.login,
        avatar: data.avatar_url,
        bio: data.bio || '',
        location: data.location || '',
        company: data.company || '',
        blog: data.blog || '',
        publicRepos: data.public_repos,
        followers: data.followers,
        following: data.following,
        joinDate: data.created_at
      };
    } catch (error) {
      console.error('Failed to fetch GitHub profile:', error);
      return null;
    }
  }
  
  async fetchSixPathsAcademyProfile(username: string, repoName: string = 'my-codesagemode-progress'): Promise<ExternalProfile | null> {
    try {
      // Try to fetch profile.json from the user's repository
      const profileUrl = `${this.rawUrl}/${username}/${repoName}/main/profile.json`;
      const response = await fetch(profileUrl);
      
      if (!response.ok) {
        return {
          username,
          repoUrl: `https://github.com/${username}/${repoName}`,
          siteUrl: `https://${username}-codesagemode.vercel.app`,
          profile: {} as UserProfile,
          lastFetched: new Date().toISOString(),
          isValid: false,
          error: 'Profile not found or repository is private'
        };
      }
      
      const profileData = await response.json();
      
      // Validate the profile structure
      if (!this.validateProfileStructure(profileData)) {
        return {
          username,
          repoUrl: `https://github.com/${username}/${repoName}`,
          siteUrl: `https://${username}-codesagemode.vercel.app`,
          profile: {} as UserProfile,
          lastFetched: new Date().toISOString(),
          isValid: false,
          error: 'Invalid profile structure'
        };
      }
      
      return {
        username,
        repoUrl: `https://github.com/${username}/${repoName}`,
        siteUrl: `https://${username}-codesagemode.vercel.app`,
        profile: profileData,
        lastFetched: new Date().toISOString(),
        isValid: true
      };
    } catch (error) {
      return {
        username,
        repoUrl: `https://github.com/${username}/${repoName}`,
        siteUrl: `https://${username}-codesagemode.vercel.app`,
        profile: {} as UserProfile,
        lastFetched: new Date().toISOString(),
        isValid: false,
        error: error instanceof Error ? error.message : 'Unknown error'
      };
    }
  }
  
  private validateProfileStructure(profile: any): boolean {
    return (
      profile &&
      profile.user &&
      typeof profile.user.name === 'string' &&
      typeof profile.user.github === 'string' &&
      typeof profile.user.totalXP === 'number' &&
      profile.progress &&
      typeof profile.progress === 'object'
    );
  }
  
  async searchSixPathsAcademyRepos(query: string): Promise<string[]> {
    try {
      const response = await fetch(
        `${this.baseUrl}/search/repositories?q=${encodeURIComponent(query + ' codesagemode')}&sort=updated&per_page=20`
      );
      
      if (!response.ok) return [];
      
      const data = await response.json();
      return data.items
        .filter((repo: any) => repo.name.includes('codesagemode'))
        .map((repo: any) => repo.owner.login);
    } catch (error) {
      console.error('Failed to search repositories:', error);
      return [];
    }
  }
}

export const githubService = new GitHubService();
```

#### Task 3.2: Peer Discovery System
**Estimated Time: 6 hours**

```typescript
// hooks/usePeerDiscovery.ts
export function usePeerDiscovery() {
  const [discoveredPeers, setDiscoveredPeers] = useState<ExternalProfile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  
  const discoverPeers = async (query: string) => {
    setIsLoading(true);
    try {
      const usernames = await githubService.searchSixPathsAcademyRepos(query);
      const profiles = await Promise.all(
        usernames.map(username => githubService.fetchSixPathsAcademyProfile(username))
      );
      
      setDiscoveredPeers(profiles.filter(p => p !== null) as ExternalProfile[]);
    } catch (error) {
      console.error('Failed to discover peers:', error);
    } finally {
      setIsLoading(false);
    }
  };
  
  const fetchSpecificPeer = async (username: string, repoName?: string) => {
    setIsLoading(true);
    try {
      const profile = await githubService.fetchSixPathsAcademyProfile(username, repoName);
      if (profile) {
        setDiscoveredPeers(prev => {
          const filtered = prev.filter(p => p.username !== username);
          return [...filtered, profile];
        });
      }
      return profile;
    } catch (error) {
      console.error('Failed to fetch peer:', error);
      return null;
    } finally {
      setIsLoading(false);
    }
  };
  
  return {
    discoveredPeers,
    isLoading,
    searchQuery,
    setSearchQuery,
    discoverPeers,
    fetchSpecificPeer
  };
}

// components/features/PeerDiscovery.tsx
export function PeerDiscovery() {
  const { discoveredPeers, isLoading, searchQuery, setSearchQuery, discoverPeers, fetchSpecificPeer } = usePeerDiscovery();
  const [manualUsername, setManualUsername] = useState('');
  const { profile: myProfile } = useProfile();
  
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      discoverPeers(searchQuery.trim());
    }
  };
  
  const handleManualAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (manualUsername.trim()) {
      fetchSpecificPeer(manualUsername.trim());
      setManualUsername('');
    }
  };
  
  return (
    <div className="space-y-6">
      {/* Search Form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center space-x-2">
            <Search className="h-5 w-5" />
            <span>Discover SixPathsAcademy Peers</span>
          </CardTitle>
          <CardDescription>
            Find other developers on their SixPathsAcademy journey
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handleSearch} className="flex space-x-2">
            <Input
              placeholder="Search by technology, location, or keyword..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="flex-1"
            />
            <Button type="submit" disabled={isLoading}>
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            </Button>
          </form>
          
          <div className="flex items-center space-x-4">
            <div className="flex-1 border-t border-muted" />
            <span className="text-sm text-muted-foreground">or</span>
            <div className="flex-1 border-t border-muted" />
          </div>
          
          <form onSubmit={handleManualAdd} className="flex space-x-2">
            <Input
              placeholder="Enter GitHub username directly..."
              value={manualUsername}
              onChange={(e) => setManualUsername(e.target.value)}
              className="flex-1"
            />
            <Button type="submit" disabled={isLoading}>
              <UserPlus className="h-4 w-4" />
            </Button>
          </form>
        </CardContent>
      </Card>
      
      {/* Discovered Peers */}
      {discoveredPeers.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Discovered Peers</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {discoveredPeers.map(peer => (
              <PeerCard
                key={peer.username}
                peer={peer}
                myProfile={myProfile}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

#### Task 3.3: Favorites System
**Estimated Time: 6 hours**

```typescript
// hooks/useFavorites.ts
export function useFavorites() {
  const { profile, updateProfile } = useProfile();
  const [favoriteProfiles, setFavoriteProfiles] = useState<ExternalProfile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  
  const favorites = profile?.preferences.favoriteDevs || [];
  
  const addFavorite = async (username: string) => {
    if (!profile || favorites.includes(username)) return;
    
    const updatedFavorites = [...favorites, username];
    updateProfile({
      preferences: {
        ...profile.preferences,
        favoriteDevs: updatedFavorites
      }
    });
    
    // Fetch the profile if not already loaded
    const existingProfile = favoriteProfiles.find(p => p.username === username);
    if (!existingProfile) {
      const peerProfile = await githubService.fetchSixPathsAcademyProfile(username);
      if (peerProfile) {
        setFavoriteProfiles(prev => [...prev, peerProfile]);
      }
    }
  };
  
  const removeFavorite = (username: string) => {
    if (!profile) return;
    
    const updatedFavorites = favorites.filter(u => u !== username);
    updateProfile({
      preferences: {
        ...profile.preferences,
        favoriteDevs: updatedFavorites
      }
    });
    
    setFavoriteProfiles(prev => prev.filter(p => p.username !== username));
  };
  
  const refreshFavorites = async () => {
    if (!profile || favorites.length === 0) return;
    
    setIsLoading(true);
    try {
      const profiles = await Promise.all(
        favorites.map(username => githubService.fetchSixPathsAcademyProfile(username))
      );
      
      setFavoriteProfiles(profiles.filter(p => p !== null) as ExternalProfile[]);
    } catch (error) {
      console.error('Failed to refresh favorites:', error);
    } finally {
      setIsLoading(false);
    }
  };
  
  const isFavorite = (username: string) => favorites.includes(username);
  
  // Load favorites on mount
  useEffect(() => {
    refreshFavorites();
  }, [profile?.preferences.favoriteDevs]);
  
  return {
    favorites,
    favoriteProfiles,
    isLoading,
    addFavorite,
    removeFavorite,
    refreshFavorites,
    isFavorite
  };
}

// components/features/FavoritesList.tsx
export function FavoritesList() {
  const { favoriteProfiles, isLoading, refreshFavorites } = useFavorites();
  const { profile: myProfile } = useProfile();
  
  if (isLoading) {
    return (
      <div className="space-y-4">
        {[...Array(3)].map((_, i) => (
          <Card key={i} className="animate-pulse">
            <CardContent className="p-6">
              <div className="flex items-center space-x-4">
                <div className="w-12 h-12 bg-muted rounded-full" />
                <div className="space-y-2 flex-1">
                  <div className="h-4 bg-muted rounded w-1/4" />
                  <div className="h-3 bg-muted rounded w-1/2" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }
  
  if (favoriteProfiles.length === 0) {
    return (
      <Card className="text-center py-12">
        <CardContent>
          <div className="space-y-4">
            <div className="text-6xl">👥</div>
            <div>
              <h3 className="text-lg font-semibold mb-2">No Favorites Yet</h3>
              <p className="text-muted-foreground">
                Discover other developers and add them to your favorites to track their progress.
              </p>
            </div>
            <Button asChild>
              <Link to="/social/discover">Discover Peers</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }
  
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">My Favorites</h2>
        <Button onClick={refreshFavorites} variant="outline" size="sm">
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>
      
      <div className="space-y-4">
        {favoriteProfiles.map(peer => (
          <FavoriteCard
            key={peer.username}
            peer={peer}
            myProfile={myProfile}
          />
        ))}
      </div>
    </div>
  );
}
```

### **Week 6: Social Dashboard & Comparison Features**

#### Task 3.4: Progress Comparison Components
**Estimated Time: 10 hours**

```typescript
// components/features/ProgressComparison.tsx
interface ComparisonData {
  myProgress: UserProfile;
  peerProgress: ExternalProfile;
  comparison: {
    paths: PathComparison[];
    overall: OverallComparison;
    achievements: AchievementComparison;
  };
}

interface PathComparison {
  pathId: string;
  pathName: string;
  myCompleted: number;
  peerCompleted: number;
  myPercentage: number;
  peerPercentage: number;
  myXP: number;
  peerXP: number;
}

export function ProgressComparison({ myProfile, peerProfile }: { myProfile: UserProfile; peerProfile: ExternalProfile }) {
  const comparisonData = useMemo(() => {
    return calculateComparison(myProfile, peerProfile);
  }, [myProfile, peerProfile]);
  
  if (!peerProfile.isValid) {
    return (
      <Card>
        <CardContent className="text-center py-8">
          <div className="text-muted-foreground">
            Unable to load peer's progress data
          </div>
        </CardContent>
      </Card>
    );
  }
  
  return (
    <div className="space-y-6">
      {/* Overall Comparison */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center space-x-2">
            <BarChart3 className="h-5 w-5" />
            <span>Overall Progress Comparison</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">{myProfile.user.totalXP}</div>
              <div className="text-sm text-muted-foreground">Your XP</div>
            </div>
            
            <div className="text-center">
              <div className="text-lg font-semibold">vs</div>
              <div className="text-sm text-muted-foreground">
                {comparisonData.overall.xpDifference > 0 ? (
                  <span className="text-green-600">+{comparisonData.overall.xpDifference} ahead</span>
                ) : comparisonData.overall.xpDifference < 0 ? (
                  <span className="text-red-600">{Math.abs(comparisonData.overall.xpDifference)} behind</span>
                ) : (
                  <span className="text-muted-foreground">Tied</span>
                )}
              </div>
            </div>
            
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-600">{peerProfile.profile.user.totalXP}</div>
              <div className="text-sm text-muted-foreground">{peerProfile.profile.user.name}'s XP</div>
            </div>
          </div>
        </CardContent>
      </Card>
      
      {/* Path-by-Path Comparison */}
      <Card>
        <CardHeader>
          <CardTitle>Six Paths Progress</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-6">
            {comparisonData.comparison.paths.map(path => (
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
      
      {/* Achievement Comparison */}
      <Card>
        <CardHeader>
          <CardTitle>Achievement Comparison</CardTitle>
        </CardHeader>
        <CardContent>
          <AchievementComparison
            myAchievements={myProfile.achievements}
            peerAchievements={peerProfile.profile.achievements}
          />
        </CardContent>
      </Card>
    </div>
  );
}

// components/features/PathComparisonRow.tsx
function PathComparisonRow({ path, myProfile, peerProfile }: PathComparisonRowProps) {
  const myProgress = myProfile.progress[path.pathId];
  const peerProgress = peerProfile.profile.progress[path.pathId];
  
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className="text-2xl">{getPathIcon(path.pathId)}</span>
          <span className="font-semibold">{path.pathName}</span>
        </div>
        <div className="text-sm text-muted-foreground">
          {path.myCompleted}/{myProgress?.total || 0} vs {path.peerCompleted}/{peerProgress?.total || 0}
        </div>
      </div>
      
      <div className="space-y-2">
        {/* My Progress */}
        <div className="flex items-center space-x-3">
          <div className="w-16 text-sm font-medium">You</div>
          <div className="flex-1">
            <Progress value={path.myPercentage} className="h-2" />
          </div>
          <div className="w-16 text-sm text-right">{path.myPercentage}%</div>
        </div>
        
        {/* Peer Progress */}
        <div className="flex items-center space-x-3">
          <div className="w-16 text-sm font-medium truncate">
            {peerProfile.profile.user.name}
          </div>
          <div className="flex-1">
            <Progress value={path.peerPercentage} className="h-2" />
          </div>
          <div className="w-16 text-sm text-right">{path.peerPercentage}%</div>
        </div>
      </div>
    </div>
  );
}
```

#### Task 3.5: Social Dashboard
**Estimated Time: 8 hours**

```typescript
// routes/social/index.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/social',
  component: SocialDashboard,
});

function SocialDashboard() {
  const { profile } = useProfile();
  const { favoriteProfiles, isLoading } = useFavorites();
  const [selectedComparison, setSelectedComparison] = useState<string | null>(null);
  
  if (!profile) {
    return (
      <div className="text-center py-12">
        <div className="text-muted-foreground">
          Please complete your profile setup to access social features.
        </div>
      </div>
    );
  }
  
  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="text-center space-y-4">
        <h1 className="text-4xl font-bold gradient-text">
          🤝 Social Dashboard
        </h1>
        <p className="text-muted-foreground max-w-2xl mx-auto">
          Connect with other SixPathsAcademy learners, compare progress, and get inspired by the community.
        </p>
      </div>
      
      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="cursor-pointer hover:shadow-lg transition-shadow">
          <CardContent className="p-6 text-center">
            <Search className="h-8 w-8 mx-auto mb-4 text-blue-500" />
            <h3 className="font-semibold mb-2">Discover Peers</h3>
            <p className="text-sm text-muted-foreground">
              Find other developers on their learning journey
            </p>
            <Button className="mt-4" asChild>
              <Link to="/social/discover">Explore</Link>
            </Button>
          </CardContent>
        </Card>
        
        <Card className="cursor-pointer hover:shadow-lg transition-shadow">
          <CardContent className="p-6 text-center">
            <Users className="h-8 w-8 mx-auto mb-4 text-green-500" />
            <h3 className="font-semibold mb-2">My Favorites</h3>
            <p className="text-sm text-muted-foreground">
              Track progress of your favorite developers
            </p>
            <Button className="mt-4" asChild>
              <Link to="/social/favorites">View All</Link>
            </Button>
          </CardContent>
        </Card>
        
        <Card className="cursor-pointer hover:shadow-lg transition-shadow">
          <CardContent className="p-6 text-center">
            <Trophy className="h-8 w-8 mx-auto mb-4 text-purple-500" />
            <h3 className="font-semibold mb-2">Global Rankings</h3>
            <p className="text-sm text-muted-foreground">
              See how you rank against the community
            </p>
            <Button className="mt-4" asChild>
              <Link to="/leaderboard">View Rankings</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
      
      {/* Favorites Overview */}
      {favoriteProfiles.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center space-x-2">
              <Heart className="h-5 w-5" />
              <span>Recent Activity from Favorites</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {favoriteProfiles.slice(0, 3).map(peer => (
                <div key={peer.username} className="flex items-center justify-between p-3 rounded-lg hover:bg-muted/50">
                  <div className="flex items-center space-x-3">
                    <img
                      src={`https://github.com/${peer.username}.png`}
                      alt={peer.username}
                      className="w-10 h-10 rounded-full"
                    />
                    <div>
                      <div className="font-semibold">{peer.profile.user.name}</div>
                      <div className="text-sm text-muted-foreground">
                        {peer.profile.user.totalXP} XP • {calculateCompletedPaths(peer.profile)} paths completed
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center space-x-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedComparison(peer.username)}
                    >
                      Compare
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      asChild
                    >
                      <a href={peer.siteUrl} target="_blank" rel="noopener noreferrer">
                        Visit
                      </a>
                    </Button>
                  </div>
                </div>
              ))}
            </div>
            
            {favoriteProfiles.length > 3 && (
              <div className="text-center mt-4">
                <Button variant="outline" asChild>
                  <Link to="/social/favorites">View All Favorites</Link>
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}
      
      {/* Community Insights */}
      <CommunityInsights />
      
      {/* Comparison Modal */}
      {selectedComparison && (
        <ComparisonModal
          myProfile={profile}
          peerProfile={favoriteProfiles.find(p => p.username === selectedComparison)!}
          onClose={() => setSelectedComparison(null)}
        />
      )}
    </div>
  );
}
```

#### Task 3.6: Social Sharing Features
**Estimated Time: 4 hours**

```typescript
// components/features/SocialSharing.tsx
export function SocialSharing({ achievement, progress }: { achievement?: Achievement; progress?: PathProgress }) {
  const { profile } = useProfile();
  const [shareUrl, setShareUrl] = useState('');
  
  const generateShareContent = () => {
    if (achievement) {
      return {
        title: `🎉 Achievement Unlocked: ${achievement.title}`,
        description: `I just earned the "${achievement.title}" achievement in SixPathsAcademy! ${achievement.description}`,
        hashtags: ['SixPathsAcademy', 'Learning', 'Achievement', 'SixPaths']
      };
    }
    
    if (progress) {
      return {
        title: `📚 Learning Progress Update`,
        description: `Just completed another tutorial in my SixPathsAcademy journey! Making progress towards mastering the Six Paths of Software Engineering.`,
        hashtags: ['SixPathsAcademy', 'Learning', 'Progress', 'SixPaths']
      };
    }
    
    return {
      title: `🎯 My SixPathsAcademy Journey`,
      description: `Check out my progress mastering the Six Paths of Software Engineering!`,
      hashtags: ['SixPathsAcademy', 'Learning', 'SixPaths']
    };
  };
  
  const shareContent = generateShareContent();
  
  const shareToTwitter = () => {
    const url = `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareContent.title)}&url=${encodeURIComponent(shareUrl)}&hashtags=${shareContent.hashtags.join(',')}`;
    window.open(url, '_blank');
  };
  
  const shareToLinkedIn = () => {
    const url = `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(shareUrl)}`;
    window.open(url, '_blank');
  };
  
  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(`${shareContent.title}\n\n${shareContent.description}\n\n${shareUrl}`);
      // Show success toast
    } catch (error) {
      console.error('Failed to copy to clipboard:', error);
    }
  };
  
  return (
    <div className="space-y-4">
      <div className="text-center space-y-2">
        <h3 className="font-semibold">Share Your Achievement!</h3>
        <p className="text-sm text-muted-foreground">
          Let others know about your SixPathsAcademy progress
        </p>
      </div>
      
      <div className="flex justify-center space-x-4">
        <Button onClick={shareToTwitter} variant="outline" size="sm">
          <Twitter className="h-4 w-4 mr-2" />
          Twitter
        </Button>
        
        <Button onClick={shareToLinkedIn} variant="outline" size="sm">
          <Linkedin className="h-4 w-4 mr-2" />
          LinkedIn
        </Button>
        
        <Button onClick={copyToClipboard} variant="outline" size="sm">
          <Copy className="h-4 w-4 mr-2" />
          Copy Link
        </Button>
      </div>
    </div>
  );
}

// components/features/ActivityFeed.tsx
export function ActivityFeed() {
  const { favoriteProfiles } = useFavorites();
  const [activities, setActivities] = useState<Activity[]>([]);
  
  useEffect(() => {
    // Generate activity feed from favorites' recent progress
    const recentActivities = favoriteProfiles.flatMap(peer => 
      generateActivitiesFromProfile(peer)
    ).sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
    
    setActivities(recentActivities.slice(0, 10));
  }, [favoriteProfiles]);
  
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center space-x-2">
          <Activity className="h-5 w-5" />
          <span>Community Activity</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {activities.map(activity => (
            <ActivityItem key={activity.id} activity={activity} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
```

## 🧪 Testing Tasks

### Task 3.7: Social Features Tests
**Estimated Time: 4 hours**

```typescript
// hooks/usePeerDiscovery.test.ts
describe('usePeerDiscovery', () => {
  it('should discover peers successfully', async () => {
    // Mock GitHub API responses
    const mockUsers = ['alice', 'bob'];
    jest.spyOn(githubService, 'searchSixPathsAcademyRepos').mockResolvedValue(mockUsers);
    
    const { result } = renderHook(() => usePeerDiscovery());
    
    await act(async () => {
      await result.current.discoverPeers('react');
    });
    
    expect(result.current.discoveredPeers).toHaveLength(2);
  });
});

// components/features/ProgressComparison.test.tsx
describe('ProgressComparison', () => {
  it('should render comparison correctly', () => {
    const mockMyProfile = createMockProfile();
    const mockPeerProfile = createMockExternalProfile();
    
    render(<ProgressComparison myProfile={mockMyProfile} peerProfile={mockPeerProfile} />);
    
    expect(screen.getByText('Overall Progress Comparison')).toBeInTheDocument();
  });
});
```

## 📁 New Files After Phase 3

```
src/
├── components/
│   ├── features/
│   │   ├── PeerDiscovery.tsx
│   │   ├── FavoritesList.tsx
│   │   ├── ProgressComparison.tsx
│   │   ├── SocialSharing.tsx
│   │   ├── ActivityFeed.tsx
│   │   └── CommunityInsights.tsx
│   └── ui/
│       ├── PeerCard.tsx
│       ├── FavoriteCard.tsx
│       └── ComparisonModal.tsx
├── hooks/
│   ├── usePeerDiscovery.ts
│   ├── useFavorites.ts
│   └── useActivityFeed.ts
├── lib/
│   ├── github-api.ts
│   ├── social-utils.ts
│   └── comparison-utils.ts
├── routes/
│   ├── social/
│   │   ├── index.tsx
│   │   ├── discover.tsx
│   │   ├── favorites.tsx
│   │   └── compare.tsx
└── types/
    └── social.ts
```

## ✅ Definition of Done

- [ ] GitHub API integration working for profile fetching
- [ ] Peer discovery system finds SixPathsAcademy users
- [ ] Favorites system allows adding/removing peers
- [ ] Progress comparison shows detailed metrics
- [ ] Social dashboard provides engaging overview
- [ ] Activity feed shows community updates
- [ ] Social sharing features work on major platforms
- [ ] All social features handle errors gracefully
- [ ] Performance optimized for multiple API calls
- [ ] Tests cover core social functionality

## 🔗 Next Phase

After completing Phase 3, proceed to [Phase 4: Advanced Features](./phase-4-advanced-features.md) to implement export/sync functionality and advanced user features.

---

**Phase 3 transforms SixPathsAcademy from a personal learning tool into a vibrant community platform that motivates and connects developers on their learning journey.** 🚀