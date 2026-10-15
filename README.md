# Welcome to our AI Bootcamp repository! 

## Start Here

### Computer Setup
1. Paste this into a Terminal window if you have a Windows laptop:
```
winget install --id Git.Git --silent --accept-source-agreements --accept-package-agreements
winget install --id OpenJS.NodeJS.LTS --silent --accept-source-agreements --accept-package-agreements
winget install --id Microsoft.VisualStudioCode --silent --accept-source-agreements --accept-package-agreements
winget install --id GitHub.CopilotApp --silent --accept-source-agreements --accept-package-agreements
```

Or paste this into a Terminal window if you have a Mac laptop:
```
brew install git
brew install node
brew install --cask visual-studio-code
brew install --cask github-copilot
```
2. Prompt Copilot to create a new code repository for you - name it what you want your project to be called.
3. Copy the AGENTS.md file in this repository.
4. Paste it into Copilot and ask it to help you create your own version of the AGENTS.md file using that template. 

### If the Mac or Windows commands above do not work for you, ask a teacher for help or follow the manual installation instructions below:

#### 1. Setup via Terminal (Command Line)
Follow the official steps on the [GitHub Git Setup Guide](https://docs.github.com/en/get-started/git-basics/set-up-git#setting-up-git) to download Git and authenticate. 

#### 2. Next, clone this repo
Pre-req: Git should be installed on your machine.

1. **Open up a terminal on your laptop.**
1. **Clone this repository locally:** `git clone <ORIGINAL_REPO_URL>`
2. **Navigate to that folder on your computer:** `cd <PATH_TO_CLONED_REPO>`
3. **Create new repo:** Go to GitHub and create a new, empty repository (do not add a README or license).
4. **Change tracking URL:** `git remote set-url origin <YOUR_NEW_GITHUB_URL>`
5. **Push everything:** `git push -u origin main`

#### 3. Setup your AI Coding Harness (GitHub Copilot App)
For an AI-native desktop environment, install the [GitHub Copilot App](https://github.com/features/ai/github-app).
This app acts as a central control center for AI agents to run builds, test code, and manage repositories directly from the desktop without needing heavy terminal configuration.

* **To connect:** Download the app, open it, and log in with a GitHub account. It handles authorization automatically.
* **To add your new repo (the one you just pushed):** Click the **+** symbol inside the app interface, click **Github repository** paste that new GitHub URL. The AI can then read the codebase, track changes, and help write code directly through chat or agent mode.

#### 4. Subscribe to GitHub Copilot Pro 
Access that link here: [GitHub Copilot Pro Plans](https://github.com/features/copilot/plans)

#### 4. Lastly, get Visual Studio Code
Install it from [here](https://code.visualstudio.com) and follow the on-screen instructions. Once it's installed, open up the local folder on your computer containing the new repository.

## 🤖 Getting Started With AI-Assisted Development Setup

This repository uses **Spec-Driven Development**. Before writing code, you and your AI assistant must review the configuration files at the "root" folder.

### Repository Architecture
```text
├── .github/
│   └── copilot-instructions.md  # Redirects GitHub Copilot to your project rules
├── AGENTS.md                    # Tailors AI agent behavior and PLAN mode workflow
├── requirements.md              # Contains project specs and GIVEN/WHEN/THEN criteria
└── README.md                    # This file
```

### File Breakdown

#### README.md (Root)
* Contains general human instructions on how to get started.

#### 🤖 AGENTS.md (Root)
* **What it does:** Outlines developer rules, terminal commands, and forces tools into **PLAN mode** before they write code.
* **Why it's at the root:** Universal open-standard location for autonomous agents (like Claude Code) to discover your project rules automatically.
  
#### 📋 requirements.md (Root)
* **What it does:** Defines the exact features, constraints, and project milestones.
* **Why it's at the root:** It acts as the primary blueprint. AI coding agents scan the root first to ensure code generation matches your project specs before editing files.

#### 🚀 .github/copilot-instructions.md
* **What it does:** Explicitly forces GitHub Copilot to use your root `AGENTS.md` and `requirements.md` files as its source of truth.
* **Why it's here:** Copilot does not naturally read root agent files by default. This file bridges that gap so Copilot Chat and inline completions respect your rules.

## Local Reminder Dashboard

Run the dependency-free, in-memory demonstration from the repository root:

```text
python -m app.dashboard
```

Open `http://127.0.0.1:8000` to filter the 20 fictional customers by dealership,
BDC agent, or language. The page previews due and holiday-deferred English/Spanish
reminders and supports review, approval/rejection, queueing, and simulated-send
actions. It never sends SMS/email or calls an external provider; restart the
process to reset the in-memory state.
