# Phase 4: Advanced Features (Weeks 7-8)

> **Implement export/sync functionality, data backup, and advanced user features for a complete SixPathsAcademy experience**

## 🎯 Phase Goals

- Build comprehensive export/import system for profile data
- Implement sync functionality with master data.json from source repository
- Create backup and restore features for user data
- Add advanced settings and customization options
- Develop offline support and PWA capabilities
- Build data migration and version management system

## 📋 Tasks Breakdown

### **Week 7: Export/Import & Data Synchronization**

#### Task 4.1: Data Export System
**Estimated Time: 8 hours**

```typescript
// lib/export-service.ts
export interface ExportOptions {
  includeProgress: boolean;
  includeAchievements: boolean;
  includePreferences: boolean;
  includeFavorites: boolean;
  format: 'json' | 'csv' | 'markdown';
  compression: boolean;
}

export interface ExportData {
  version: string;
  exportedAt: string;
  exportedBy: string;
  metadata: {
    totalTutorials: number;
    totalXP: number;
    pathsCompleted: number;
    achievementsCount: number;
  };
  profile: UserProfile;
  additionalData?: {
    favoriteProfiles?: ExternalProfile[];
    customSettings?: Record<string, any>;
  };
}

class ExportService {
  private readonly version = '1.0.0';
  
  async exportProfile(profile: UserProfile, options: ExportOptions): Promise<Blob> {
    const exportData: ExportData = {
      version: this.version,
      exportedAt: new Date().toISOString(),
      exportedBy: profile.user.github,
      metadata: {
        totalTutorials: Object.values(profile.progress).reduce((sum, p) => sum + p.completed, 0),
        totalXP: profile.user.totalXP,
        pathsCompleted: Object.values(profile.progress).filter(p => p.completed === p.total).length,
        achievementsCount: profile.achievements.length
      },
      profile: this.filterProfileData(profile, options)
    };
    
    // Add additional data if requested
    if (options.includeFavorites) {
      exportData.additionalData = {
        favoriteProfiles: await this.fetchFavoriteProfiles(profile.preferences.favoriteDevs),
        customSettings: this.getCustomSettings()
      };
    }
    
    switch (options.format) {
      case 'json':
        return this.exportAsJSON(exportData, options.compression);
      case 'csv':
        return this.exportAsCSV(exportData);
      case 'markdown':
        return this.exportAsMarkdown(exportData);
      default:
        throw new Error(`Unsupported export format: ${options.format}`);
    }
  }
  
  private filterProfileData(profile: UserProfile, options: ExportOptions): UserProfile {
    const filtered = { ...profile };
    
    if (!options.includeProgress) {
      filtered.progress = {};
    }
    
    if (!options.includeAchievements) {
      filtered.achievements = [];
    }
    
    if (!options.includePreferences) {
      filtered.preferences = {
        favoriteDevs: [],
        notifications: true,
        publicProfile: true
      };
    }
    
    return filtered;
  }
  
  private async exportAsJSON(data: ExportData, compression: boolean): Promise<Blob> {
    const jsonString = JSON.stringify(data, null, 2);
    
    if (compression) {
      // Use compression library if available
      const compressed = await this.compressData(jsonString);
      return new Blob([compressed], { type: 'application/gzip' });
    }
    
    return new Blob([jsonString], { type: 'application/json' });
  }
  
  private async exportAsCSV(data: ExportData): Promise<Blob> {
    const csvData = this.convertToCSV(data);
    return new Blob([csvData], { type: 'text/csv' });
  }
  
  private async exportAsMarkdown(data: ExportData): Promise<Blob> {
    const markdown = this.generateMarkdownReport(data);
    return new Blob([markdown], { type: 'text/markdown' });
  }
  
  private generateMarkdownReport(data: ExportData): string {
    const { profile, metadata } = data;
    
    return `# SixPathsAcademy Progress Report
    
## 👤 Profile
- **Name**: ${profile.user.name}
- **GitHub**: [@${profile.user.github}](https://github.com/${profile.user.github})
- **Current Level**: ${profile.user.currentLevel}
- **Total XP**: ${profile.user.totalXP}
- **Joined**: ${new Date(profile.user.joinDate).toLocaleDateString()}

## 📊 Progress Summary
- **Total Tutorials Completed**: ${metadata.totalTutorials}
- **Paths Mastered**: ${metadata.pathsCompleted}/6
- **Achievements Earned**: ${metadata.achievementsCount}

## 🎯 Six Paths Progress

${Object.entries(profile.progress).map(([pathId, progress]) => `
### ${this.getPathName(pathId)}
- **Progress**: ${progress.completed}/${progress.total} (${Math.round(progress.completed / progress.total * 100)}%)
- **XP Earned**: ${progress.xpEarned}
- **Started**: ${new Date(progress.startDate).toLocaleDateString()}
${progress.completionDate ? `- **Completed**: ${new Date(progress.completionDate).toLocaleDateString()}` : ''}

**Completed Tutorials**:
${progress.completedTutorials.map(t => `- ${this.getTutorialTitle(t)}`).join('\n')}
`).join('\n')}

## 🏆 Achievements

${profile.achievements.map(achievement => `
### ${achievement.icon} ${achievement.title}
${achievement.description}
*Unlocked on ${new Date(achievement.unlockedAt).toLocaleDateString()}*
`).join('\n')}

---
*Report generated on ${new Date(data.exportedAt).toLocaleString()}*
*SixPathsAcademy v${data.version}*
`;
  }
  
  async importProfile(file: File): Promise<UserProfile> {
    const fileContent = await file.text();
    
    try {
      const importData: ExportData = JSON.parse(fileContent);
      
      // Validate import data
      this.validateImportData(importData);
      
      // Handle version compatibility
      if (importData.version !== this.version) {
        return this.migrateProfile(importData);
      }
      
      return importData.profile;
    } catch (error) {
      throw new Error(`Failed to import profile: ${error}`);
    }
  }
  
  private validateImportData(data: ExportData): void {
    if (!data.version || !data.profile) {
      throw new Error('Invalid import data format');
    }
    
    if (!data.profile.user || !data.profile.progress) {
      throw new Error('Missing required profile data');
    }
  }
  
  private migrateProfile(data: ExportData): UserProfile {
    // Handle migration between versions
    // This would contain logic to upgrade older profile formats
    return data.profile;
  }
}

export const exportService = new ExportService();
```

#### Task 4.2: Data Sync System
**Estimated Time: 10 hours**

```typescript
// lib/sync-service.ts
export interface SyncOptions {
  sourceRepo: string;
  sourceBranch: string;
  forceUpdate: boolean;
  backupCurrent: boolean;
}

export interface SyncResult {
  success: boolean;
  updated: boolean;
  changes: {
    newTutorials: string[];
    updatedTutorials: string[];
    removedTutorials: string[];
    newPaths: string[];
    updatedPaths: string[];
  };
  backupCreated?: string;
  error?: string;
}

class SyncService {
  private readonly defaultSource = 'https://raw.githubusercontent.com/quanhua92/SixPathsAcademy/main';
  
  async syncWithSource(options: SyncOptions): Promise<SyncResult> {
    try {
      // Create backup if requested
      let backupId: string | undefined;
      if (options.backupCurrent) {
        backupId = await this.createBackup();
      }
      
      // Fetch latest data from source
      const [latestConfig, latestData] = await Promise.all([
        this.fetchLatestConfig(options),
        this.fetchLatestData(options)
      ]);
      
      // Compare with current data
      const currentConfig = await this.getCurrentConfig();
      const currentData = await this.getCurrentData();
      
      const changes = this.calculateChanges(currentData, latestData);
      
      // Apply updates if there are changes
      if (this.hasChanges(changes)) {
        await this.applyUpdates(latestConfig, latestData);
        
        return {
          success: true,
          updated: true,
          changes,
          backupCreated: backupId
        };
      }
      
      return {
        success: true,
        updated: false,
        changes,
        backupCreated: backupId
      };
    } catch (error) {
      return {
        success: false,
        updated: false,
        changes: {
          newTutorials: [],
          updatedTutorials: [],
          removedTutorials: [],
          newPaths: [],
          updatedPaths: []
        },
        error: error instanceof Error ? error.message : 'Unknown sync error'
      };
    }
  }
  
  private async fetchLatestConfig(options: SyncOptions): Promise<Config> {
    const url = `${this.defaultSource}/data/config.json`;
    const response = await fetch(url);
    
    if (!response.ok) {
      throw new Error(`Failed to fetch config: ${response.statusText}`);
    }
    
    return response.json();
  }
  
  private async fetchLatestData(options: SyncOptions): Promise<any> {
    const url = `${this.defaultSource}/data/data.json`;
    const response = await fetch(url);
    
    if (!response.ok) {
      throw new Error(`Failed to fetch data: ${response.statusText}`);
    }
    
    return response.json();
  }
  
  private calculateChanges(currentData: any, latestData: any): SyncResult['changes'] {
    const changes: SyncResult['changes'] = {
      newTutorials: [],
      updatedTutorials: [],
      removedTutorials: [],
      newPaths: [],
      updatedPaths: []
    };
    
    // Compare tutorials
    const currentTutorials = new Set(Object.keys(currentData.tutorials || {}));
    const latestTutorials = new Set(Object.keys(latestData.tutorials || {}));
    
    // Find new tutorials
    for (const tutorialId of latestTutorials) {
      if (!currentTutorials.has(tutorialId)) {
        changes.newTutorials.push(tutorialId);
      } else {
        // Check if tutorial was updated
        const current = currentData.tutorials[tutorialId];
        const latest = latestData.tutorials[tutorialId];
        
        if (JSON.stringify(current) !== JSON.stringify(latest)) {
          changes.updatedTutorials.push(tutorialId);
        }
      }
    }
    
    // Find removed tutorials
    for (const tutorialId of currentTutorials) {
      if (!latestTutorials.has(tutorialId)) {
        changes.removedTutorials.push(tutorialId);
      }
    }
    
    // Compare paths
    const currentPaths = new Set(Object.keys(currentData.paths || {}));
    const latestPaths = new Set(Object.keys(latestData.paths || {}));
    
    for (const pathId of latestPaths) {
      if (!currentPaths.has(pathId)) {
        changes.newPaths.push(pathId);
      } else {
        const current = currentData.paths[pathId];
        const latest = latestData.paths[pathId];
        
        if (JSON.stringify(current) !== JSON.stringify(latest)) {
          changes.updatedPaths.push(pathId);
        }
      }
    }
    
    return changes;
  }
  
  private hasChanges(changes: SyncResult['changes']): boolean {
    return (
      changes.newTutorials.length > 0 ||
      changes.updatedTutorials.length > 0 ||
      changes.removedTutorials.length > 0 ||
      changes.newPaths.length > 0 ||
      changes.updatedPaths.length > 0
    );
  }
  
  private async applyUpdates(config: Config, data: any): Promise<void> {
    // Update local storage with new data
    localStorage.setItem('codesagemode-config', JSON.stringify(config));
    localStorage.setItem('codesagemode-data', JSON.stringify(data));
    
    // Trigger data refresh in the app
    window.dispatchEvent(new CustomEvent('codesagemode-data-updated'));
  }
  
  private async createBackup(): Promise<string> {
    const backupId = `backup_${Date.now()}`;
    const currentData = {
      config: await this.getCurrentConfig(),
      data: await this.getCurrentData(),
      profile: JSON.parse(localStorage.getItem('codesagemode-profile') || '{}')
    };
    
    localStorage.setItem(`codesagemode-backup-${backupId}`, JSON.stringify(currentData));
    return backupId;
  }
  
  async getBackups(): Promise<Array<{ id: string; createdAt: Date; size: number }>> {
    const backups = [];
    
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith('codesagemode-backup-')) {
        const backupId = key.replace('codesagemode-backup-', '');
        const data = localStorage.getItem(key);
        
        if (data) {
          backups.push({
            id: backupId,
            createdAt: new Date(parseInt(backupId.split('_')[1])),
            size: new Blob([data]).size
          });
        }
      }
    }
    
    return backups.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
  }
  
  async restoreBackup(backupId: string): Promise<void> {
    const backupData = localStorage.getItem(`codesagemode-backup-${backupId}`);
    
    if (!backupData) {
      throw new Error('Backup not found');
    }
    
    const { config, data, profile } = JSON.parse(backupData);
    
    localStorage.setItem('codesagemode-config', JSON.stringify(config));
    localStorage.setItem('codesagemode-data', JSON.stringify(data));
    localStorage.setItem('codesagemode-profile', JSON.stringify(profile));
    
    // Trigger app refresh
    window.location.reload();
  }
  
  async deleteBackup(backupId: string): Promise<void> {
    localStorage.removeItem(`codesagemode-backup-${backupId}`);
  }
}

export const syncService = new SyncService();
```

### **Week 8: Advanced Settings & PWA Features**

#### Task 4.3: Advanced Settings System
**Estimated Time: 8 hours**

```typescript
// routes/settings.tsx
export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage,
});

function SettingsPage() {
  const { profile, updateProfile } = useProfile();
  const [activeTab, setActiveTab] = useState('general');
  const [backups, setBackups] = useState<Array<{ id: string; createdAt: Date; size: number }>>([]);
  
  useEffect(() => {
    syncService.getBackups().then(setBackups);
  }, []);
  
  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground">
          Customize your SixPathsAcademy experience and manage your data
        </p>
      </div>
      
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-5">
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="progress">Progress</TabsTrigger>
          <TabsTrigger value="social">Social</TabsTrigger>
          <TabsTrigger value="data">Data</TabsTrigger>
          <TabsTrigger value="advanced">Advanced</TabsTrigger>
        </TabsList>
        
        <TabsContent value="general" className="space-y-6">
          <GeneralSettings profile={profile} onUpdate={updateProfile} />
        </TabsContent>
        
        <TabsContent value="progress" className="space-y-6">
          <ProgressSettings profile={profile} onUpdate={updateProfile} />
        </TabsContent>
        
        <TabsContent value="social" className="space-y-6">
          <SocialSettings profile={profile} onUpdate={updateProfile} />
        </TabsContent>
        
        <TabsContent value="data" className="space-y-6">
          <DataSettings profile={profile} backups={backups} onBackupsChange={setBackups} />
        </TabsContent>
        
        <TabsContent value="advanced" className="space-y-6">
          <AdvancedSettings profile={profile} onUpdate={updateProfile} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// components/settings/DataSettings.tsx
function DataSettings({ profile, backups, onBackupsChange }: DataSettingsProps) {
  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [exportOptions, setExportOptions] = useState<ExportOptions>({
    includeProgress: true,
    includeAchievements: true,
    includePreferences: true,
    includeFavorites: true,
    format: 'json',
    compression: false
  });
  
  const handleExport = async () => {
    if (!profile) return;
    
    setIsExporting(true);
    try {
      const blob = await exportService.exportProfile(profile, exportOptions);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `codesagemode-export-${new Date().toISOString().split('T')[0]}.${exportOptions.format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Export failed:', error);
    } finally {
      setIsExporting(false);
    }
  };
  
  const handleImport = async (file: File) => {
    setIsImporting(true);
    try {
      const importedProfile = await exportService.importProfile(file);
      // Show confirmation dialog before applying
      if (confirm('This will replace your current progress. Are you sure?')) {
        localStorage.setItem('codesagemode-profile', JSON.stringify(importedProfile));
        window.location.reload();
      }
    } catch (error) {
      console.error('Import failed:', error);
    } finally {
      setIsImporting(false);
    }
  };
  
  const handleSync = async () => {
    setIsSyncing(true);
    try {
      const result = await syncService.syncWithSource({
        sourceRepo: 'quanhua92/SixPathsAcademy',
        sourceBranch: 'main',
        forceUpdate: false,
        backupCurrent: true
      });
      
      if (result.success) {
        if (result.updated) {
          alert(`Sync successful! Updated ${result.changes.newTutorials.length + result.changes.updatedTutorials.length} tutorials.`);
        } else {
          alert('Already up to date!');
        }
        
        if (result.backupCreated) {
          const updatedBackups = await syncService.getBackups();
          onBackupsChange(updatedBackups);
        }
      } else {
        alert(`Sync failed: ${result.error}`);
      }
    } catch (error) {
      console.error('Sync failed:', error);
    } finally {
      setIsSyncing(false);
    }
  };
  
  return (
    <div className="space-y-6">
      {/* Export Section */}
      <Card>
        <CardHeader>
          <CardTitle>Export Data</CardTitle>
          <CardDescription>
            Download your SixPathsAcademy progress and settings
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Include in Export</Label>
              <div className="space-y-2">
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="include-progress"
                    checked={exportOptions.includeProgress}
                    onCheckedChange={(checked) => 
                      setExportOptions(prev => ({ ...prev, includeProgress: checked as boolean }))
                    }
                  />
                  <Label htmlFor="include-progress">Progress Data</Label>
                </div>
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="include-achievements"
                    checked={exportOptions.includeAchievements}
                    onCheckedChange={(checked) => 
                      setExportOptions(prev => ({ ...prev, includeAchievements: checked as boolean }))
                    }
                  />
                  <Label htmlFor="include-achievements">Achievements</Label>
                </div>
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="include-favorites"
                    checked={exportOptions.includeFavorites}
                    onCheckedChange={(checked) => 
                      setExportOptions(prev => ({ ...prev, includeFavorites: checked as boolean }))
                    }
                  />
                  <Label htmlFor="include-favorites">Favorites</Label>
                </div>
              </div>
            </div>
            
            <div className="space-y-2">
              <Label>Export Format</Label>
              <Select
                value={exportOptions.format}
                onValueChange={(value) => 
                  setExportOptions(prev => ({ ...prev, format: value as ExportOptions['format'] }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="json">JSON</SelectItem>
                  <SelectItem value="csv">CSV</SelectItem>
                  <SelectItem value="markdown">Markdown Report</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          
          <Button onClick={handleExport} disabled={isExporting}>
            {isExporting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Exporting...
              </>
            ) : (
              <>
                <Download className="h-4 w-4 mr-2" />
                Export Data
              </>
            )}
          </Button>
        </CardContent>
      </Card>
      
      {/* Import Section */}
      <Card>
        <CardHeader>
          <CardTitle>Import Data</CardTitle>
          <CardDescription>
            Restore your SixPathsAcademy progress from a backup file
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="border-2 border-dashed border-muted-foreground/25 rounded-lg p-6">
              <input
                type="file"
                accept=".json"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleImport(file);
                }}
                className="hidden"
                id="import-file"
              />
              <label
                htmlFor="import-file"
                className="cursor-pointer flex flex-col items-center space-y-2"
              >
                <Upload className="h-8 w-8 text-muted-foreground" />
                <div className="text-sm text-center">
                  <span className="font-medium">Click to upload</span>
                  <br />
                  <span className="text-muted-foreground">JSON files only</span>
                </div>
              </label>
            </div>
            
            {isImporting && (
              <div className="text-center text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin inline mr-2" />
                Processing import...
              </div>
            )}
          </div>
        </CardContent>
      </Card>
      
      {/* Sync Section */}
      <Card>
        <CardHeader>
          <CardTitle>Sync with Source</CardTitle>
          <CardDescription>
            Update your local tutorial data with the latest from the source repository
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="text-sm text-muted-foreground">
              <p>This will fetch the latest tutorials, paths, and configuration from the main SixPathsAcademy repository.</p>
              <p className="mt-1">A backup will be created automatically before applying updates.</p>
            </div>
            
            <Button onClick={handleSync} disabled={isSyncing}>
              {isSyncing ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Syncing...
                </>
              ) : (
                <>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Sync Now
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>
      
      {/* Backup Management */}
      <Card>
        <CardHeader>
          <CardTitle>Backup Management</CardTitle>
          <CardDescription>
            Manage your automatic backups and restore points
          </CardDescription>
        </CardHeader>
        <CardContent>
          <BackupList backups={backups} onBackupsChange={onBackupsChange} />
        </CardContent>
      </Card>
    </div>
  );
}
```

#### Task 4.4: PWA Implementation
**Estimated Time: 6 hours**

```typescript
// lib/pwa-service.ts
export class PWAService {
  private registration: ServiceWorkerRegistration | null = null;
  
  async init(): Promise<void> {
    if ('serviceWorker' in navigator) {
      try {
        this.registration = await navigator.serviceWorker.register('/sw.js');
        console.log('Service Worker registered:', this.registration);
      } catch (error) {
        console.error('Service Worker registration failed:', error);
      }
    }
  }
  
  async checkForUpdates(): Promise<boolean> {
    if (!this.registration) return false;
    
    await this.registration.update();
    return !!this.registration.waiting;
  }
  
  async activateUpdate(): Promise<void> {
    if (!this.registration?.waiting) return;
    
    this.registration.waiting.postMessage({ type: 'SKIP_WAITING' });
    window.location.reload();
  }
  
  async getInstallPrompt(): Promise<BeforeInstallPromptEvent | null> {
    return new Promise((resolve) => {
      const handler = (e: Event) => {
        e.preventDefault();
        window.removeEventListener('beforeinstallprompt', handler);
        resolve(e as BeforeInstallPromptEvent);
      };
      
      window.addEventListener('beforeinstallprompt', handler);
      
      // Timeout after 5 seconds
      setTimeout(() => {
        window.removeEventListener('beforeinstallprompt', handler);
        resolve(null);
      }, 5000);
    });
  }
  
  async promptInstall(): Promise<boolean> {
    const installPrompt = await this.getInstallPrompt();
    if (!installPrompt) return false;
    
    const result = await installPrompt.prompt();
    return result.outcome === 'accepted';
  }
}

// public/sw.js
const CACHE_NAME = 'codesagemode-v1';
const urlsToCache = [
  '/',
  '/static/js/bundle.js',
  '/static/css/main.css',
  '/data/config.json',
  '/data/data.json',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request)
      .then((response) => {
        // Return cached version or fetch from network
        return response || fetch(event.request);
      })
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
```

#### Task 4.5: Offline Support
**Estimated Time: 8 hours**

```typescript
// hooks/useOfflineSupport.ts
export function useOfflineSupport() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [syncQueue, setSyncQueue] = useState<Array<{ id: string; action: string; data: any }>>([]);
  
  useEffect(() => {
    const handleOnline = () => {
      setIsOnline(true);
      processSyncQueue();
    };
    
    const handleOffline = () => {
      setIsOnline(false);
    };
    
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);
  
  const addToSyncQueue = (action: string, data: any) => {
    const queueItem = {
      id: Date.now().toString(),
      action,
      data,
      timestamp: Date.now()
    };
    
    setSyncQueue(prev => [...prev, queueItem]);
    
    // Store in local storage for persistence
    const stored = JSON.parse(localStorage.getItem('codesagemode-sync-queue') || '[]');
    stored.push(queueItem);
    localStorage.setItem('codesagemode-sync-queue', JSON.stringify(stored));
  };
  
  const processSyncQueue = async () => {
    if (!isOnline || syncQueue.length === 0) return;
    
    const queue = [...syncQueue];
    setSyncQueue([]);
    
    for (const item of queue) {
      try {
        await processSyncItem(item);
      } catch (error) {
        console.error('Failed to process sync item:', error);
        // Re-add failed items to queue
        addToSyncQueue(item.action, item.data);
      }
    }
    
    // Clear successfully processed items from local storage
    localStorage.removeItem('codesagemode-sync-queue');
  };
  
  const processSyncItem = async (item: { action: string; data: any }) => {
    switch (item.action) {
      case 'update-progress':
        // Sync progress updates
        break;
      case 'add-favorite':
        // Sync favorite additions
        break;
      case 'submit-to-rankings':
        // Sync ranking submissions
        break;
      default:
        console.warn('Unknown sync action:', item.action);
    }
  };
  
  return {
    isOnline,
    syncQueue,
    addToSyncQueue
  };
}

// components/features/OfflineIndicator.tsx
export function OfflineIndicator() {
  const { isOnline, syncQueue } = useOfflineSupport();
  
  if (isOnline && syncQueue.length === 0) return null;
  
  return (
    <div className="fixed bottom-4 right-4 z-50">
      <Card className="w-80">
        <CardContent className="p-4">
          <div className="flex items-center space-x-3">
            {isOnline ? (
              <div className="flex items-center space-x-2">
                <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                <span className="text-sm text-green-600">Online</span>
              </div>
            ) : (
              <div className="flex items-center space-x-2">
                <div className="w-2 h-2 bg-red-500 rounded-full" />
                <span className="text-sm text-red-600">Offline</span>
              </div>
            )}
            
            {syncQueue.length > 0 && (
              <div className="flex items-center space-x-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-sm text-muted-foreground">
                  {syncQueue.length} items queued
                </span>
              </div>
            )}
          </div>
          
          {!isOnline && (
            <p className="text-sm text-muted-foreground mt-2">
              Your progress is being saved locally and will sync when you're back online.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

## 🧪 Testing Tasks

### Task 4.6: Advanced Features Tests
**Estimated Time: 4 hours**

```typescript
// lib/export-service.test.ts
describe('ExportService', () => {
  it('should export profile as JSON', async () => {
    const mockProfile = createMockProfile();
    const options: ExportOptions = {
      includeProgress: true,
      includeAchievements: true,
      includePreferences: true,
      includeFavorites: false,
      format: 'json',
      compression: false
    };
    
    const blob = await exportService.exportProfile(mockProfile, options);
    const text = await blob.text();
    const exported = JSON.parse(text);
    
    expect(exported.profile.user.name).toBe(mockProfile.user.name);
    expect(exported.version).toBeDefined();
  });
  
  it('should import profile correctly', async () => {
    const mockExport = createMockExport();
    const file = new File([JSON.stringify(mockExport)], 'test.json');
    
    const imported = await exportService.importProfile(file);
    
    expect(imported.user.name).toBe(mockExport.profile.user.name);
  });
});
```

## 📁 New Files After Phase 4

```
src/
├── components/
│   ├── settings/
│   │   ├── GeneralSettings.tsx
│   │   ├── ProgressSettings.tsx
│   │   ├── SocialSettings.tsx
│   │   ├── DataSettings.tsx
│   │   └── AdvancedSettings.tsx
│   ├── features/
│   │   ├── OfflineIndicator.tsx
│   │   ├── InstallPrompt.tsx
│   │   └── BackupList.tsx
│   └── ui/
│       ├── ExportDialog.tsx
│       └── SyncStatus.tsx
├── lib/
│   ├── export-service.ts
│   ├── sync-service.ts
│   ├── pwa-service.ts
│   └── migration-service.ts
├── hooks/
│   ├── useOfflineSupport.ts
│   ├── useExportImport.ts
│   └── usePWA.ts
├── public/
│   ├── sw.js
│   └── manifest.json
└── types/
    └── advanced.ts
```

## ✅ Definition of Done

- [ ] Export system supports multiple formats (JSON, CSV, Markdown)
- [ ] Import system validates and migrates profile data
- [ ] Sync system updates local data from source repository
- [ ] Backup system creates and manages restore points
- [ ] Advanced settings provide comprehensive customization
- [ ] PWA features enable offline usage and app installation
- [ ] Service worker caches essential resources
- [ ] Offline support queues actions for later sync
- [ ] All advanced features handle errors gracefully
- [ ] Performance optimized for large data operations
- [ ] Tests cover critical functionality

## 🔗 Next Phase

After completing Phase 4, proceed to [Phase 5: Polish & Deploy](./phase-5-polish-deploy.md) to enhance the UI, optimize performance, and prepare for production deployment.

---

**Phase 4 elevates SixPathsAcademy from a simple learning tracker to a comprehensive, professional-grade platform with advanced data management and offline capabilities.** 🚀