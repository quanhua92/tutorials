# SixPathsAcademy.com - Master Development Plan

> **Master all dimensions of software engineering through six complementary paths**

## 🎯 Project Overview

SixPathsAcademy.com is a gamified learning platform that transforms The Engineer's Playbook into an interactive, community-driven experience. Built with React, TanStack Router, Tailwind CSS, and ShadCN UI, it enables developers to track their progress through the Six Paths of Software Engineering while building a community around shared learning.

## 🏗️ Architecture Philosophy

### **Decentralized Progress Tracking**
- Each developer owns their learning journey via forked repositories
- Personal progress stored in JSON files within their own repos
- Client-only application deployable to Vercel
- No vendor lock-in - developers control their data

### **Community-Driven Learning**
- Peer comparison through GitHub repo crawling
- Favorites system for following other developers
- Optional global rankings for competitive learning
- Social features that encourage knowledge sharing

### **Lightweight & Scalable**
- Static site generation for maximum performance
- Zero database dependencies - fully Git-based architecture
- Edge-first deployment strategy
- Cost-effective scaling through static hosting

## 🚀 Development Phases

### **Phase 1: Foundation** (Weeks 1-2)
Core application setup with routing, data models, and basic UI components.
- [📋 Phase 1 Tasks](./phase-1-foundation.md)

### **Phase 2: Progress Tracking & AI Assistant** (Weeks 3-4)
User profile system with progress visualization, local storage, and the Sensei Roku AI assistant.
- [📋 Phase 2 Tasks](./phase-2-progress-tracking.md)

### **Phase 3: Social Features** (Weeks 5-6)
Peer comparison system and external repository crawling.
- [📋 Phase 3 Tasks](./phase-3-social-features.md)

### **Phase 4: Advanced Features** (Weeks 7-8)
Export/import functionality and data synchronization.
- [📋 Phase 4 Tasks](./phase-4-advanced-features.md)

### **Phase 5: Polish & Deploy** (Weeks 9-10)
UI enhancements, performance optimization, and deployment.
- [📋 Phase 5 Tasks](./phase-5-polish-deploy.md)

### **Phase 6: Global Rankings** (Weeks 11-12)
Git-based ranking system with GitHub Actions aggregation.
- [📋 Phase 6 Tasks](./phase-6-global-rankings.md)

## 📁 Core Data Structure

### **JSON Files**
- **`config.json`** - Global app configuration and settings
- **`data.json`** - Six Paths tutorial data and metadata
- **`profile.json`** - User progress and achievements
- **`metadata.json`** - Repository and deployment metadata

📖 [Complete Data Schemas](./data-schemas.md)

## 🧩 Component Architecture

### **Page Components**
- Dashboard, Profile, Leaderboard, Tutorial Detail, Settings

### **Feature Components**
- Progress visualization, peer comparison, achievement system
- **🥋 Sensei Roku** - AI-powered learning assistant with contextual guidance

### **UI Components**
- ShadCN UI-based design system with custom gamification elements

📖 [Component Specifications](./component-specs.md)

## 🚀 Deployment Strategy

### **Individual Forks**
- Vercel deployment for personal progress tracking
- Automatic deployments on repository updates
- Custom domain support for personal branding

### **Main SixPathsAcademy Site**
- Global rankings through Git-based aggregation
- Community features and statistics
- Zero infrastructure costs - fully Git-based

📖 [Deployment Guide](./deployment-guide.md)

## 🎮 Gamification Elements

### **Six Paths Progression**
- **📚 Foundations Path** - Core concepts and data structures
- **🏗️ Systems Path** - Distributed systems and architecture
- **🧠 Algorithms Path** - Advanced algorithms and problem-solving
- **⚡ Performance Path** - Optimization and efficiency techniques
- **🔬 Specialized Topics** - Advanced specialized data structures
- **🌐 Distributed Systems & Architecture** - Advanced distributed patterns
- **🛠️ Operations & Reliability** - Production systems and reliability

### **Achievement System**
- Path completion badges
- Skill mastery indicators
- Community contribution recognition
- Learning streak tracking

### **Social Features**
- Peer progress comparison
- Favorite developers system
- Global leaderboards
- Achievement showcases

## 💻 Tech Stack

### **Frontend**
- **React 18** - Component framework
- **TanStack Router** - Type-safe routing
- **Tailwind CSS** - Utility-first styling
- **ShadCN UI** - Component library
- **TypeScript** - Type safety
- **Vercel AI SDK** - Client-side AI chat integration
- **React Markdown** - Rich text rendering for AI responses

### **Data Layer**
- **GitHub API** - Repository crawling and data fetching
- **Static JSON Files** - Configuration and tutorial data
- **Local Storage** - User progress and preferences
- **Git-based Rankings** - Community leaderboards via GitHub Actions

### **Deployment**
- **Vercel** - Static site hosting
- **GitHub Actions** - CI/CD and rankings aggregation
- **CDN** - Global content delivery
- **Zero Backend** - Client-only application

## 🎯 Success Metrics

### **User Engagement**
- Path completion rates
- Daily active users
- Tutorial engagement time
- Community participation

### **Learning Outcomes**
- Skill progression tracking
- Knowledge retention indicators
- Practical application metrics
- Peer learning effectiveness

### **Community Growth**
- Repository forks and stars
- Leaderboard participation
- Social feature usage
- Content contributions

## 🥋 Sensei Roku - AI Learning Mentor

**Sensei Roku** is SixPathsAcademy's intelligent AI assistant that acts as your personal software engineering mentor. Named after the Japanese word for "six" (representing the Six Paths methodology), this context-aware companion provides personalized guidance throughout your learning journey.

### **Key Features:**
- **🧠 Context-Aware**: Understands your current tutorial, progress level, and learning path
- **🔒 Privacy-First**: Uses your own API key, stored locally with base64 encoding
- **🎨 Flexible Modes**: Sidebar, floating chat, or embedded assistance
- **⚡ Quick Help**: Pre-built contextual questions for faster learning
- **🌐 Provider Agnostic**: Works with OpenAI, Claude, local models, or any OpenAI-compatible API

### **How It Works:**
1. Configure your OpenAI-compatible API credentials in Settings
2. Sensei Roku appears throughout the platform ready to help
3. Get instant explanations, examples, and guidance tailored to your current study topic
4. Ask questions in plain English - no technical jargon required

**Perfect for**: Students who want an intelligent study companion that understands both their current lesson and overall progress, providing personalized mentorship without compromising privacy or data control.

*Your path to software engineering mastery, guided by AI wisdom.* 🥋

---

## 🔄 Future Enhancements

### **Phase 7+: Advanced Features**
- **Enhanced AI Features** - Advanced prompt templates and learning analytics
- **Video Integration** - Tutorial walkthroughs and explanations
- **Practice Challenges** - Coding exercises and assessments
- **Mentorship System** - Connect learners with experienced developers
- **Team Learning** - Study groups and collaborative features
- **Mobile App** - Native mobile experience
- **Offline Mode** - Download content for offline learning

### **Integration Possibilities**
- **GitHub Codespaces** - One-click development environments
- **VS Code Extension** - In-editor progress tracking
- **Discord Bot** - Community engagement and notifications
- **Slack Integration** - Team learning and progress sharing

## 📚 Resources

### **Documentation**
- [TanStack Router Docs](https://tanstack.com/router)
- [ShadCN UI Components](https://ui.shadcn.com/)
- [Tailwind CSS Reference](https://tailwindcss.com/docs)
- [Vercel Deployment Guide](https://vercel.com/docs)

### **Inspiration**
- [The Engineer's Playbook](https://github.com/quanhua92/the-engineers-playbook)
- [LeetCode](https://leetcode.com) - Progress tracking
- [Codecademy](https://codecademy.com) - Interactive learning
- [GitHub Profile README](https://github.com) - Personal showcases

---

## 🚀 Getting Started

1. **Fork the repository** and clone to your local machine
2. **Follow Phase 1 tasks** to set up the development environment
3. **Customize your profile.json** with your learning goals
4. **Deploy to Vercel** to start tracking your progress
5. **Share your journey** with the community

**Ready to begin your journey to Software Engineering Sage Mode?** 🌟

*Choose your path. Master the fundamentals. Achieve true understanding.*