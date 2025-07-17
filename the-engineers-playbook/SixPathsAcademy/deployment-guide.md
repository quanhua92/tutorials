# Deployment Guide

> **Complete guide for deploying SixPathsAcademy to production with Vercel and setting up the development environment**

## 📋 Overview

This guide provides step-by-step instructions for deploying SixPathsAcademy to production using Vercel, setting up development environments, and managing the application lifecycle.

## 🚀 Quick Start Deployment

### Prerequisites

- Node.js 18+ installed
- Git repository access
- Vercel account (free tier available)
- GitHub account

### 1. Fork and Clone Repository

```bash
# Fork the repository on GitHub
# Then clone your fork
git clone https://github.com/YOUR_USERNAME/my-codesagemode-progress.git
cd my-codesagemode-progress

# Install dependencies
npm install
```

### 2. Local Development Setup

```bash
# Start development server
npm run dev

# Open in browser
open http://localhost:5173
```

### 3. Deploy to Vercel

**Option A: Deploy via Vercel CLI**

```bash
# Install Vercel CLI
npm install -g vercel

# Login to Vercel
vercel login

# Deploy
vercel --prod
```

**Option B: Deploy via GitHub Integration**

1. Go to [vercel.com](https://vercel.com)
2. Click "New Project"
3. Import from GitHub
4. Select your repository
5. Configure build settings (auto-detected)
6. Deploy

## 🛠️ Detailed Setup Instructions

### Development Environment Setup

#### 1. System Requirements

```bash
# Check Node.js version
node --version  # Should be 18.0.0 or higher
npm --version   # Should be 9.0.0 or higher

# Install pnpm (optional but recommended)
npm install -g pnpm
```

#### 2. Project Structure Setup

```bash
# Create project from template
npx create-react-app my-codesagemode --template typescript
cd my-codesagemode

# Or use Vite (recommended)
npm create vite@latest my-codesagemode -- --template react-ts
cd my-codesagemode
npm install
```

#### 3. Install Dependencies

```bash
# Core dependencies
npm install @tanstack/react-router @tanstack/router-devtools
npm install tailwindcss @tailwindcss/typography
npm install @radix-ui/react-slot @radix-ui/react-separator
npm install lucide-react class-variance-authority clsx tailwind-merge
npm install framer-motion

# Development dependencies
npm install -D @types/node @types/react @types/react-dom
npm install -D @testing-library/react @testing-library/jest-dom
npm install -D @testing-library/user-event vitest jsdom
npm install -D prettier eslint-config-prettier
npm install -D @typescript-eslint/eslint-plugin @typescript-eslint/parser
```

#### 4. Configuration Files

**tsconfig.json**
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"],
      "@/components/*": ["./src/components/*"],
      "@/lib/*": ["./src/lib/*"],
      "@/hooks/*": ["./src/hooks/*"],
      "@/types/*": ["./src/types/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

**tailwind.config.js**
```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: 0 },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: 0 },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
```

**vite.config.ts**
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', '@tanstack/react-router'],
          ui: ['@radix-ui/react-slot', 'class-variance-authority'],
          utils: ['clsx', 'tailwind-merge', 'lucide-react']
        }
      }
    }
  },
  server: {
    port: 5173,
    open: true
  }
})
```

## 🌐 Vercel Deployment Configuration

### 1. Vercel Configuration File

**vercel.json**
```json
{
  "version": 2,
  "builds": [
    {
      "src": "package.json",
      "use": "@vercel/static-build",
      "config": {
        "distDir": "dist"
      }
    }
  ],
  "routes": [
    {
      "src": "/data/(.*)",
      "headers": {
        "Cache-Control": "s-maxage=86400, stale-while-revalidate=43200"
      }
    },
    {
      "src": "/assets/(.*)",
      "headers": {
        "Cache-Control": "s-maxage=31536000, immutable"
      }
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ],
  "env": {
    "VITE_APP_NAME": "SixPathsAcademy",
    "VITE_APP_VERSION": "1.0.0",
    "VITE_API_URL": "https://api.codesagemode.com"
  },
  "functions": {
    "api/health.ts": {
      "maxDuration": 10
    }
  }
}
```

### 2. Build Scripts

**package.json**
```json
{
  "name": "codesagemode",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "preview": "vite preview",
    "test": "vitest",
    "test:ui": "vitest --ui",
    "test:coverage": "vitest run --coverage",
    "type-check": "tsc --noEmit",
    "format": "prettier --write src/**/*.{ts,tsx}",
    "prepare": "husky install"
  },
  "dependencies": {
    "@tanstack/react-router": "^1.15.0",
    "@tanstack/router-devtools": "^1.15.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "tailwindcss": "^3.4.0",
    "framer-motion": "^11.0.0",
    "lucide-react": "^0.316.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.2.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.55",
    "@types/react-dom": "^18.2.19",
    "@typescript-eslint/eslint-plugin": "^6.21.0",
    "@typescript-eslint/parser": "^6.21.0",
    "@vitejs/plugin-react": "^4.2.1",
    "typescript": "^5.2.2",
    "vite": "^5.1.0",
    "vitest": "^1.2.0",
    "prettier": "^3.2.0",
    "eslint": "^8.56.0",
    "eslint-config-prettier": "^9.1.0"
  }
}
```

### 3. Environment Variables

Create `.env.local` file for development:
```bash
# Application
VITE_APP_NAME=SixPathsAcademy
VITE_APP_VERSION=1.0.0
VITE_APP_ENVIRONMENT=development

# GitHub Integration
VITE_GITHUB_TOKEN=ghp_your_token_here
VITE_GITHUB_REPO=your-username/your-repo

# Analytics (optional)
VITE_ANALYTICS_ID=your_analytics_id
```

Configure in Vercel dashboard:
- Go to your project settings
- Navigate to "Environment Variables"
- Add production values

### 4. Custom Domain Setup

**Add Custom Domain in Vercel:**
1. Go to project settings
2. Navigate to "Domains"
3. Add your domain (e.g., `yourname-codesagemode.com`)
4. Configure DNS records as instructed

**DNS Configuration:**
```
Type: CNAME
Name: @
Value: cname.vercel-dns.com
```

## 🔧 Advanced Configuration

### 1. CI/CD Pipeline with GitHub Actions

**.github/workflows/deploy.yml**
```yaml
name: Deploy to Vercel

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '18'
          cache: 'npm'
          
      - name: Install dependencies
        run: npm ci
        
      - name: Run type checking
        run: npm run type-check
        
      - name: Run linting
        run: npm run lint
        
      - name: Run tests
        run: npm run test
        
      - name: Build project
        run: npm run build
        
      - name: Deploy to Vercel
        uses: amondnet/vercel-action@v25
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
          working-directory: ./
```

### 2. Performance Optimization

**Build Optimization:**
```typescript
// vite.config.ts
export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          router: ['@tanstack/react-router'],
          ui: ['@radix-ui/react-slot', 'framer-motion'],
          utils: ['clsx', 'tailwind-merge', 'lucide-react']
        }
      }
    },
    chunkSizeWarningLimit: 1000,
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true
      }
    }
  }
})
```

**Service Worker (PWA):**
```typescript
// public/sw.js
const CACHE_NAME = 'codesagemode-v1';
const urlsToCache = [
  '/',
  '/static/js/bundle.js',
  '/static/css/main.css',
  '/data/config.json',
  '/data/data.json'
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
        return response || fetch(event.request);
      })
  );
});
```

### 3. Analytics and Monitoring

**Web Vitals Tracking:**
```typescript
// lib/analytics.ts
export function trackWebVitals(metric: any) {
  console.log(metric);
  
  // Send to analytics service
  if (typeof gtag !== 'undefined') {
    gtag('event', metric.name, {
      event_category: 'Web Vitals',
      value: Math.round(metric.value),
      event_label: metric.id,
      non_interaction: true
    });
  }
}

// main.tsx
import { getCLS, getFID, getFCP, getLCP, getTTFB } from 'web-vitals';

getCLS(trackWebVitals);
getFID(trackWebVitals);
getFCP(trackWebVitals);
getLCP(trackWebVitals);
getTTFB(trackWebVitals);
```

## 🐛 Debugging and Troubleshooting

### Common Issues

**1. Build Failures**
```bash
# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install

# Check for type errors
npm run type-check

# Check for linting errors
npm run lint
```

**2. Deployment Issues**
```bash
# Check Vercel logs
vercel logs

# Local production build test
npm run build
npm run preview
```

**3. Performance Issues**
```bash
# Analyze bundle size
npm run build -- --analyze

# Check for unused dependencies
npx depcheck
```

### Debug Configuration

**VS Code Settings (.vscode/settings.json):**
```json
{
  "typescript.preferences.importModuleSpecifier": "relative",
  "editor.formatOnSave": true,
  "editor.defaultFormatter": "esbenp.prettier-vscode",
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": true
  },
  "files.associations": {
    "*.css": "tailwindcss"
  }
}
```

**Launch Configuration (.vscode/launch.json):**
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Launch Chrome",
      "request": "launch",
      "type": "chrome",
      "url": "http://localhost:5173",
      "webRoot": "${workspaceFolder}/src"
    }
  ]
}
```

## 📊 Monitoring and Analytics

### 1. Performance Monitoring

**Vercel Analytics Integration:**
```typescript
// lib/analytics.ts
import { track } from '@vercel/analytics';

export function trackEvent(event: string, data?: Record<string, any>) {
  track(event, data);
}

export function trackPageView(page: string) {
  track('page_view', { page });
}

export function trackTutorialComplete(tutorialId: string) {
  track('tutorial_complete', { tutorial_id: tutorialId });
}
```

### 2. Error Tracking

**Sentry Integration:**
```typescript
// lib/sentry.ts
import * as Sentry from '@sentry/react';

Sentry.init({
  dsn: process.env.VITE_SENTRY_DSN,
  environment: process.env.VITE_APP_ENVIRONMENT,
  integrations: [
    new Sentry.BrowserTracing(),
  ],
  tracesSampleRate: 1.0,
});

export { Sentry };
```

### 3. Health Checks

**API Route (api/health.ts):**
```typescript
import { VercelRequest, VercelResponse } from '@vercel/node';

export default function handler(req: VercelRequest, res: VercelResponse) {
  const healthCheck = {
    status: 'OK',
    timestamp: new Date().toISOString(),
    uptime: process.uptime(),
    environment: process.env.NODE_ENV,
    version: process.env.npm_package_version
  };
  
  res.status(200).json(healthCheck);
}
```

## 🔄 Data Management

### 1. Data Syncing

**Automatic Data Updates:**
```typescript
// lib/data-sync.ts
export class DataSyncService {
  private static instance: DataSyncService;
  
  static getInstance(): DataSyncService {
    if (!DataSyncService.instance) {
      DataSyncService.instance = new DataSyncService();
    }
    return DataSyncService.instance;
  }
  
  async syncData(): Promise<void> {
    try {
      const response = await fetch('/api/sync');
      const data = await response.json();
      
      if (data.updated) {
        localStorage.setItem('codesagemode-data', JSON.stringify(data.content));
        window.location.reload();
      }
    } catch (error) {
      console.error('Data sync failed:', error);
    }
  }
}
```

### 2. Backup Strategy

**GitHub Backup:**
```typescript
// lib/backup.ts
export async function backupToGitHub(profile: UserProfile) {
  const token = process.env.VITE_GITHUB_TOKEN;
  if (!token) return;
  
  const content = btoa(JSON.stringify(profile, null, 2));
  
  await fetch(`https://api.github.com/repos/${username}/${repo}/contents/profile.json`, {
    method: 'PUT',
    headers: {
      'Authorization': `token ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      message: 'Update profile data',
      content,
      sha: await getFileSha('profile.json')
    })
  });
}
```

## 🚀 Production Deployment Checklist

### Pre-deployment
- [ ] All tests passing
- [ ] Type checking clean
- [ ] Linting issues resolved
- [ ] Performance optimized
- [ ] Security audit completed
- [ ] Environment variables configured
- [ ] Error tracking setup
- [ ] Analytics configured

### Deployment
- [ ] Production build successful
- [ ] Vercel deployment completed
- [ ] Custom domain configured
- [ ] SSL certificate active
- [ ] CDN caching configured
- [ ] Health checks passing

### Post-deployment
- [ ] Functionality testing
- [ ] Performance monitoring
- [ ] Error tracking active
- [ ] Analytics data flowing
- [ ] Backup systems operational
- [ ] Documentation updated

## 🔐 Security Considerations

### 1. Environment Variables

```bash
# Never commit these to version control
VITE_GITHUB_TOKEN=ghp_your_token_here
VITE_SENTRY_DSN=your_sentry_dsn
VITE_ANALYTICS_ID=your_analytics_id
```

### 2. Content Security Policy

**Headers in vercel.json:**
```json
{
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        {
          "key": "Content-Security-Policy",
          "value": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:"
        }
      ]
    }
  ]
}
```

### 3. API Security

```typescript
// lib/api-security.ts
export function validateRequest(req: any) {
  const origin = req.headers.origin;
  const allowedOrigins = [
    'https://your-domain.com',
    'https://your-domain.vercel.app'
  ];
  
  return allowedOrigins.includes(origin);
}
```

## 📱 Progressive Web App (PWA)

### 1. Manifest Configuration

**public/manifest.json:**
```json
{
  "name": "SixPathsAcademy",
  "short_name": "SixPathsAcademy",
  "description": "Master software engineering through the Six Paths",
  "start_url": "/",
  "display": "standalone",
  "theme_color": "#3b82f6",
  "background_color": "#ffffff",
  "icons": [
    {
      "src": "/icon-192x192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/icon-512x512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

### 2. Service Worker Registration

```typescript
// lib/pwa.ts
export function registerServiceWorker() {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js')
        .then((registration) => {
          console.log('SW registered: ', registration);
        })
        .catch((registrationError) => {
          console.log('SW registration failed: ', registrationError);
        });
    });
  }
}
```

## 📈 Scaling Considerations

### 1. Performance Monitoring

- Set up Vercel Analytics
- Monitor Core Web Vitals
- Track bundle size changes
- Monitor API response times

### 2. Cost Optimization

- Optimize bundle sizes
- Use efficient caching strategies
- Monitor bandwidth usage
- Consider CDN optimization

### 3. User Experience

- Implement progressive enhancement
- Add offline functionality
- Optimize for mobile devices
- Ensure accessibility compliance

---

**This comprehensive deployment guide ensures a smooth, secure, and performant deployment of SixPathsAcademy to production.** 🚀

*Follow this guide step-by-step to deploy your personalized SixPathsAcademy application successfully.*