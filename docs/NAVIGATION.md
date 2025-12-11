# Artemis Navigation Guide

> **AI Management Platform** - Unified proxy for LLM API calls with usage tracking, cost analytics, and multi-provider support

Version: 1.0.0
URL: https://artemis.jettaintelligence.com
Last Updated: December 2025

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication & Access](#authentication--access)
3. [Navigation Structure](#navigation-structure)
4. [Core Concepts](#core-concepts)
5. [Page Reference](#page-reference)
6. [User Flows](#user-flows)
7. [Navigation Tips](#navigation-tips)
8. [Keyboard Shortcuts](#keyboard-shortcuts)

---

## Overview

Artemis is a centralized AI management platform that serves as a unified proxy for all LLM API calls. It provides:

- **Usage Tracking** - Monitor all API requests across your organization
- **Cost Analytics** - Real-time cost tracking with detailed breakdowns
- **Multi-Provider Support** - OpenAI, Anthropic, Google, Perplexity, OpenRouter
- **Organization & Group Management** - Hierarchical access control
- **API Key Management** - Secure key storage and rotation
- **Real-time Health Monitoring** - Provider uptime and performance tracking

### Key Features

- Dark theme UI with cream/navy color scheme
- Organization → Group → Keys hierarchy
- SSO integration with Jetta SSO (optional)
- Localhost auto-login for development
- Real-time analytics dashboards
- Interactive chat interface for testing

---

## Authentication & Access

### Login Methods

#### Production (SSO Enabled)
- **URL**: `/login`
- **Method**: Jetta SSO integration
- Seamless authentication across all Jetta apps
- Shared cookie on `.jettaintelligence.com` domain

#### Development (Localhost Mode)
- **Auto-login**: Automatically logs in as test user
- **Email**: `localhost@artemis.local`
- No password required when running on localhost

#### Manual Login
- **URL**: `/login`
- **Fields**: Email and password
- Used when SSO is disabled

### Registration
- **URL**: `/register`
- **Fields**: Email and password
- Creates new user account
- Automatically creates session and redirects to dashboard

### Logout
- **URL**: `/logout`
- Clears local session cookies
- Redirects to SSO logout if SSO is enabled
- Returns to landing page

---

## Navigation Structure

### Primary Navigation (Top Bar)

The top navigation bar is always visible and provides access to all major sections:

```
[Artemis Logo] | Dashboard | Chat | Logs | Health | API Keys | Providers | Groups | Guide | AI Agent | API Docs | [User Menu ▼]
```

#### Navigation Items (Left to Right)

1. **Artemis** (Logo) - Returns to landing page or dashboard
2. **Dashboard** - Analytics and usage overview
3. **Chat** - Interactive chat interface for testing
4. **Logs** - Detailed request history
5. **Health** - Provider health status monitoring
6. **API Keys** - Manage Artemis API keys
7. **Providers** - Configure provider API keys
8. **Groups** - Team and access management
9. **Guide** - Setup and integration guide
10. **AI Agent** - Agent-specific documentation
11. **API Docs** - API reference documentation

### User Menu (Dropdown)

Click your email in the top-right corner to access:

**Organization Switcher** (hover to expand)
- Shows current organization or "No organization"
- Lists all organizations you belong to
- "Clear selection" option

**Group Switcher** (hover to expand, only when org selected)
- Shows current group or "All Groups"
- Lists all groups you're a member of
- "All Groups" option to view aggregate data

**Account Options**
- Settings - User preferences and organization management
- Logout - End session

---

## Core Concepts

### Organizational Hierarchy

```
User
  ├── Organization A
  │   ├── Group 1 (Team A)
  │   │   ├── API Keys
  │   │   └── Provider Keys
  │   └── Group 2 (Team B)
  │       ├── API Keys
  │       └── Provider Keys
  └── Organization B
      └── Group 1 (Default)
          ├── API Keys
          └── Provider Keys
```

### Key Concepts

**Organization**
- Top-level entity for your company
- Contains multiple groups
- Owner can manage all settings
- Members can be added to specific groups

**Group**
- Sub-team within an organization
- Isolates API keys and usage
- Members have roles: Owner, Admin, Member
- Default group created automatically

**API Key** (Artemis Key)
- Your application uses this to call Artemis
- Group-scoped (isolated per team)
- Tracks all usage and costs
- Can override provider selection

**Provider Key** (LLM Provider API Key)
- Your actual OpenAI, Anthropic, etc. API key
- Stored encrypted in database
- Group-scoped for security
- Can be shared across multiple Artemis keys

**Usage Log**
- Every API request creates a log entry
- Tracks: model, tokens, cost, latency, provider
- Filterable by key, provider, app, model
- Retained for historical analysis

**Provider Account**
- Container for provider keys
- Associates keys with a specific provider (OpenAI, Anthropic, etc.)
- Group-scoped for isolation

---

## Page Reference

### 1. Landing Page

**URL**: `/`

**Purpose**: Marketing page for unauthenticated users

**Behavior**:
- Shows when not logged in
- Redirects to `/dashboard` if already authenticated
- In localhost mode, auto-redirects to dashboard

**Actions**:
- Login button
- Register button
- Learn more about features

**Screenshot Description**:
*Hero section with Artemis branding, feature highlights (usage tracking, cost analytics, multi-provider support), CTA buttons for Login and Get Started*

---

### 2. Dashboard

**URL**: `/dashboard`

**Purpose**: Main analytics hub showing usage metrics and costs

**Sections**:

#### Summary Cards (Top Row)
- **Total Requests** - Count of all API calls
- **Total Tokens** - Input + output tokens with breakdown
- **Total Cost** - Dollars spent with input/output split
- **Avg Latency** - Average response time in milliseconds

#### Charts (4-column grid)
- **Daily Usage** - Line chart showing requests over time
- **Input vs Output Cost** - Doughnut chart of cost distribution
- **Cost by Provider** - Doughnut chart (OpenAI, Anthropic, etc.)
- **Cost by App** - Doughnut chart by X-App-Id header

#### Filters (Top Right)
- **User** - Filter by team member (in group/org mode)
- **API Key** - Filter by specific Artemis key
- **Provider Account** - Filter by provider key
- **Provider** - Filter by OpenAI, Anthropic, etc.
- **App ID** - Filter by application
- **Period** - Last 7/14/30 days, QTD, YTD, All Time

#### Tables

**Usage by API Key**
- Key name, requests, tokens, cost
- Click row to filter dashboard by that key

**Usage by Provider Account**
- Account name, provider, requests, cost
- Shows which provider keys are being used

**Usage by Provider** (if data exists)
- Provider name, requests, input/output tokens, costs
- Detailed breakdown of token and cost split

**Top Models** (if data exists)
- Model name (clickable for pricing details), provider, requests, cost
- Sorted by usage

**Usage by App** (if data exists)
- App ID, requests, tokens, costs
- Apps identified via X-App-Id header
- Click row to filter by app

**Usage by Group** (only in "All Groups" mode)
- Group name, requests, tokens, cost
- Compare usage across teams

#### Quick Links (Bottom)
- Navigate to API Keys page
- Navigate to Providers page
- Navigate to Usage Logs page

**Context Awareness**:
- Shows organization name in header if selected
- Displays "(All Groups)" if viewing aggregate data
- Filters automatically apply to current context

**Screenshot Description**:
*Dashboard with 4 summary cards at top, row of colorful charts below, filters in top-right, and detailed tables showing usage breakdowns by key, provider, and model*

---

### 3. Chat Interface

**URL**: `/chat`

**Purpose**: Interactive testing interface for Artemis proxy

**Sections**:

#### API Key Selector (Top)
- Dropdown to select which Artemis API key to use
- Grouped by team if in "All Groups" mode
- Shows key name and group

#### Provider Selector
- Choose provider (OpenAI, Anthropic, Google, etc.)
- Only shows providers you have keys for
- Updates model list dynamically

#### Model Selector
- Choose specific model
- Filtered by selected provider
- Shows model capabilities (vision, reasoning, etc.)

#### Chat Interface
- Message input textarea
- Send button
- Chat history displays below
- Shows:
  - Your messages
  - AI responses
  - Token counts (input/output)
  - Cost per request
  - Latency

#### Settings Panel
- Temperature slider
- Max tokens input
- System prompt (optional)
- Advanced options (stream, reasoning, etc.)

**Features**:
- Real-time streaming responses
- Token usage displayed after each message
- Cost calculation shown
- Clear chat button
- Copy response button

**Screenshot Description**:
*Chat interface with key/provider/model selectors at top, message history in center with alternating user/assistant messages showing token counts and costs, input box at bottom, settings panel on right*

---

### 4. Usage Logs

**URL**: `/logs`

**Purpose**: Detailed request history with filtering and pagination

**Sections**:

#### Filters (Top)
- **API Key** - Filter by specific key
- **Provider** - OpenAI, Anthropic, etc.
- **App ID** - Filter by application
- **Model** - Filter by model name

#### Logs Table
Columns:
- **Timestamp** - When request was made
- **API Key** - Which key was used
- **Provider** - LLM provider
- **Model** - Specific model
- **App ID** - Application identifier
- **Tokens** - Input/output counts
- **Cost** - Dollar amount
- **Latency** - Response time in ms
- **Status** - Success/error

#### Pagination
- 50 logs per page
- Page navigation at bottom
- Shows total count

**Actions**:
- Click log row to expand details
- View full request/response (if enabled)
- Export logs (future feature)

**Context Awareness**:
- Only shows logs for current group context
- In "All Groups" mode, shows logs from all accessible groups

**Screenshot Description**:
*Table of API requests with columns for timestamp, key, provider, model, tokens, cost, and latency. Filters at top, pagination at bottom. Each row expandable for details.*

---

### 5. App Logs

**URL**: `/app-logs`

**Purpose**: Application error logging (localhost mode only)

**Sections**:

#### Filters
- **Source** - frontend, backend
- **Level** - error, warn, info, debug
- **Error Type** - Specific error types

#### Logs Table
Columns:
- **Timestamp**
- **Source** - Frontend or backend
- **Level** - Severity
- **Message** - Error message
- **Error Type** - Exception type
- **Page** - Where error occurred
- **Component** - Specific component

#### Details (Expandable)
- Stack trace
- User agent
- Extra metadata

**Availability**: Only in localhost development mode

**Screenshot Description**:
*Debug console showing frontend and backend errors with timestamps, severity levels, and expandable stack traces*

---

### 6. API Keys Management

**URL**: `/api-keys`

**Purpose**: Manage Artemis API keys (what your apps use)

**Sections**:

#### Create New Key (Top)
- **Name** input field
- **Create** button
- Key name must be unique within group

#### Success Modal (After Creation)
- Shows full API key ONE TIME ONLY
- Copy to clipboard button
- Warning: "This is the only time you'll see this key"

#### API Keys List

**Columns**:
- **Name** - Key identifier
- **Key Prefix** - First/last few characters
- **Group** - Which team owns it (in All Groups mode)
- **Created** - Creation date
- **Last Used** - Most recent request
- **Status** - Active or Revoked

**Actions per Key**:
- **Reveal** - Show full key (if encrypted)
- **Revoke** - Disable key (cannot be undone)
- **Configure Overrides** - Set provider preferences

#### Provider Key Overrides (Per API Key)
- Override default provider key selection
- Set specific provider key per provider
- Example: Use "Production OpenAI Key" instead of default

**Context Awareness**:
- Cannot create keys in "All Groups" mode (must select specific group)
- Only shows keys from current group context
- Group name shown in All Groups mode

**Screenshot Description**:
*List of API keys with name, prefix, creation date, and action buttons. "Create New Key" form at top. Modal showing newly created key with copy button.*

---

### 7. Providers Management

**URL**: `/providers`

**Purpose**: Configure LLM provider API keys (OpenAI, Anthropic, etc.)

**Sections**:

#### Provider Tabs
- OpenAI
- Anthropic
- Google (Gemini)
- Perplexity
- OpenRouter

#### For Each Provider:

**Provider Accounts**
- **Account Name** - Friendly identifier
- **Model Count** - Number of models synced
- **Status** - Active/Inactive
- **Created** - Creation date

**Actions per Account**:
- **Add Key** - Add a new API key to this account
- **Sync Models** - Fetch latest model list and pricing
- **Delete** - Remove account (if no keys exist)

**Provider Keys List**
- **Name** - Key identifier
- **Account** - Which provider account it belongs to
- **Group** - Team ownership (in All Groups mode)
- **Created** - Creation date
- **Status** - Active/Revoked

**Actions per Key**:
- **Reveal** - Show full API key (decrypt)
- **Test** - Verify key works
- **Revoke** - Disable key

#### Add Provider Account Modal
- **Provider** - Dropdown selection
- **Account Name** - Friendly name
- **Create** button

#### Add Provider Key Modal
- **Account** - Select account
- **Key Name** - Friendly identifier
- **API Key** - Paste provider's actual key
- **Save** button (encrypts and stores)

**Model Syncing**:
- Fetches available models from provider
- Updates pricing information
- Shows last sync timestamp
- Required for accurate cost calculations

**Context Awareness**:
- Cannot create keys in "All Groups" mode
- Only shows accounts/keys from current group
- Group name displayed in All Groups mode

**Screenshot Description**:
*Tabbed interface showing provider accounts (OpenAI, Anthropic, etc.). Each account has a list of API keys with reveal/test/revoke actions. "Add Account" and "Sync Models" buttons.*

---

### 8. Groups Management

**URL**: `/groups`

**Purpose**: Manage teams and access control within organization

**Sections**:

#### Create New Group (Top)
- **Name** input
- **Description** textarea (optional)
- **Create Group** button
- Only visible to admins/owners

#### Groups List

**For Each Group**:

**Group Card**
- **Name** - Group identifier
- **Description** - Purpose/details
- **Member Count** - Number of members
- **Default Badge** - If set as org default
- **Your Role** - Owner, Admin, or Member

**Actions (if admin/owner)**:
- **Edit** - Change name/description
- **Delete** - Remove group (if no keys exist)
- **Set as Default** - Make default for new members

**Members Section**
- **User Email** - Member identifier
- **Role** - Owner, Admin, Member
- **Joined** - Date added
- **Actions**:
  - Change Role (owners only)
  - Remove Member

**Add Member Form** (if admin/owner)
- **Email** input
- **Role** dropdown (Member, Admin, Owner)
- **Add** button
- User must exist in Artemis

#### Role Permissions

**Owner**
- Full control over group
- Add/remove members
- Change roles
- Delete group
- Manage API keys and provider keys

**Admin**
- Add/remove members (except owners)
- Manage API keys and provider keys
- Cannot delete group

**Member**
- View group resources
- Use API keys
- Cannot manage members or keys

**Restrictions**:
- Must have org selected to view groups
- Cannot delete default group
- Cannot remove last owner
- Only owners can promote to admin/owner

**Screenshot Description**:
*Card-based layout showing groups with member counts and descriptions. Each card expandable to show member list with roles and management actions. "Create Group" form at top.*

---

### 9. Settings

**URL**: `/settings`

**Purpose**: User preferences and organization management

**Sections**:

#### User Settings
- **Email** - Display only, cannot change
- **Display Name** - Update name (future)
- **Preferences** - UI settings (future)

#### Organization Management

**Your Organizations**
- List of organizations you own or belong to
- **Organization Name**
- **Your Role** - Owner or Member
- **Member Count**
- **Created Date**

**Actions per Org**:
- **View/Switch** - Make it the active org
- **Leave** - Remove yourself (if not owner)

**Create New Organization**
- **Organization Name** input
- **Create** button
- You become the owner automatically
- Default group created automatically

#### Demo Data (Development)
- **Load Demo Data** button
- Creates sample organization with:
  - API keys
  - Provider keys
  - Usage logs
  - Multiple groups
- Only visible in localhost mode

**Screenshot Description**:
*Settings page with user profile section at top, list of organizations below, and "Create Organization" form. Each organization card shows member count and role.*

---

### 10. Setup Guide

**URL**: `/guide`

**Purpose**: Integration instructions and code examples

**Sections**:

#### Quick Start
1. Create an API key
2. Add provider keys
3. Use Artemis proxy in your app

#### Integration Code Examples

**OpenAI (Python)**
```python
from openai import OpenAI

client = OpenAI(
    base_url="https://artemis.jettaintelligence.com/v1",
    api_key="art_xxxxxxxxxxxx"
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

**Anthropic (Python)**
```python
from anthropic import Anthropic

client = Anthropic(
    base_url="https://artemis.jettaintelligence.com/v1",
    api_key="art_xxxxxxxxxxxx"
)

message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

**cURL Examples**
- OpenAI-compatible endpoint
- Anthropic endpoint
- Request headers
- Response format

#### App Identification
- Setting `X-App-Id` header
- Benefits for tracking
- Example usage

#### Best Practices
- Key rotation strategy
- Error handling
- Rate limiting
- Cost optimization tips

**Screenshot Description**:
*Documentation page with code blocks showing integration examples for different languages and providers. Copy buttons next to each code snippet.*

---

### 11. AI Agent Guide

**URL**: `/agent-guide`

**Purpose**: Documentation for AI agents using Artemis

**Sections**:

#### For AI Assistants
- How to authenticate
- Recommended patterns
- Error handling
- Usage tracking

#### Code Examples
- Agent-specific integration patterns
- Streaming responses
- Function calling
- Multi-turn conversations

**Screenshot Description**:
*Specialized guide with examples tailored for AI agents and autonomous systems*

---

### 12. Health Status

**URL**: `/health-status`

**Purpose**: Real-time provider availability monitoring

**Sections**:

#### Overall Status Banner
- **All Systems Operational** (green)
- **Degraded Performance** (yellow)
- **Outage Detected** (red)

#### Provider Status Cards

**For Each Provider (OpenAI, Anthropic, Google, etc.)**:
- **Status Indicator** - Green/yellow/red dot
- **Provider Name**
- **Last Checked** - Timestamp of last health check
- **Response Time** - Average latency
- **Success Rate** - Percentage of successful requests
- **Recent Errors** - Count of recent failures

#### Status Levels
- **Healthy** - All checks passing (green)
- **Degraded** - Some failures or slow responses (yellow)
- **Unhealthy** - Multiple failures or timeouts (red)

#### History Graph (Future)
- Uptime percentage over time
- Latency trends
- Incident timeline

**Auto-Refresh**: Page updates every 30 seconds

**Screenshot Description**:
*Status dashboard showing provider health cards with green/yellow/red indicators, response times, and success rates. Overall status banner at top.*

---

### 13. API Documentation

**URL**: `/docs`

**Purpose**: FastAPI auto-generated API reference

**Sections**:

#### Available Endpoints

**Authentication**
- `POST /register` - Create account
- `POST /login` - Authenticate
- `GET /logout` - End session
- `POST /switch-org` - Change organization
- `POST /switch-group` - Change group

**LLM Proxy**
- `POST /v1/chat/completions` - OpenAI-compatible chat
- `POST /v1/messages` - Anthropic-compatible messages
- `GET /v1/models` - List available models

**Management**
- API Keys endpoints
- Provider Keys endpoints
- Usage logs endpoints
- Analytics endpoints

#### Try It Out
- Interactive API testing
- Authentication with bearer token
- Example requests and responses
- Schema definitions

**Screenshot Description**:
*FastAPI Swagger UI showing expandable API endpoint sections with request/response schemas, try-it-out buttons, and example payloads*

---

## User Flows

### Flow 1: Getting Started (New User)

1. **Register** → `/register`
   - Enter email and password
   - Submit form

2. **Auto-login** → `/dashboard`
   - Redirected automatically
   - Empty dashboard (no data yet)

3. **Create Organization** → `/settings`
   - Click "Settings" in nav
   - Enter organization name
   - Click "Create Organization"
   - Default group created automatically

4. **Add Provider Key** → `/providers`
   - Click "Providers" in nav
   - Select provider tab (e.g., OpenAI)
   - Click "Add Account"
   - Enter account name
   - Click "Create"
   - Click "Add Key" on new account
   - Enter key name and paste API key
   - Click "Save"

5. **Create API Key** → `/api-keys`
   - Click "API Keys" in nav
   - Enter key name
   - Click "Create"
   - **IMPORTANT**: Copy the displayed key (only shown once)
   - Save securely

6. **Test Integration** → `/chat`
   - Click "Chat" in nav
   - Select your API key
   - Select provider
   - Choose model
   - Send test message
   - Verify response

7. **View Usage** → `/dashboard`
   - Click "Dashboard"
   - See request count, tokens, cost
   - Check usage by provider

**Success**: You're now tracking all AI usage through Artemis!

---

### Flow 2: Adding Team Members

1. **Create Group** → `/groups`
   - Click "Groups" in nav
   - Ensure organization is selected (top-right menu)
   - Enter group name and description
   - Click "Create Group"

2. **Add Provider Keys to Group**
   - Ensure group is selected (top-right menu)
   - Go to `/providers`
   - Create account and add provider keys
   - Keys are group-scoped automatically

3. **Create API Keys for Group**
   - Go to `/api-keys`
   - Create new API key
   - Key is scoped to current group

4. **Invite Team Member**
   - Go to `/groups`
   - Find your group
   - Click "Add Member"
   - Enter member's email (they must have an Artemis account)
   - Select role (Member, Admin, Owner)
   - Click "Add"

5. **Member Switches to Group**
   - Member logs in
   - Clicks user menu (top-right)
   - Hovers over organization
   - Selects your organization
   - Hovers over group
   - Selects the group

6. **Member Can Now**:
   - View group's API keys (but not reveal them unless admin)
   - Use group's API keys in their apps
   - View usage logs for group
   - See analytics for group

---

### Flow 3: Monitoring Costs

1. **Set Time Period** → `/dashboard`
   - Go to Dashboard
   - Select period filter (7 days, 30 days, QTD, etc.)

2. **Review Summary Cards**
   - Total requests
   - Total tokens (input/output split)
   - Total cost (input/output split)
   - Average latency

3. **Analyze Charts**
   - **Daily Usage**: Spot trends over time
   - **Cost by Provider**: Which provider costs most
   - **Cost by App**: Which application uses most
   - **Input vs Output**: Token distribution

4. **Drill Down by API Key**
   - Scroll to "Usage by API Key" table
   - Click on any key to filter entire dashboard

5. **Drill Down by Provider**
   - Use provider filter dropdown
   - View usage for specific provider only

6. **Check Detailed Logs** → `/logs`
   - Click "Logs" in navigation
   - Apply filters (key, provider, app, model)
   - Review individual requests
   - Identify expensive calls

7. **Set Up Alerts** (Future Feature)
   - Configure cost thresholds
   - Email notifications
   - Slack integration

---

### Flow 4: Switching Between Organizations/Groups

#### Switch Organization

1. Click your email in top-right corner
2. Hover over organization name in dropdown
3. Nested menu appears showing all orgs
4. Click desired organization
5. Page refreshes with new context
6. All data now filtered to that org

#### Switch Group (Within Current Org)

1. Click your email in top-right corner
2. Hover over "Group:" section in dropdown
3. Nested menu shows all groups
4. Click desired group
5. Dashboard updates to show group data
6. All keys/logs filtered to that group

#### View All Groups

1. Click your email in top-right corner
2. Hover over "Group:" section
3. Click "All Groups"
4. Dashboard shows aggregate data across all groups
5. "Usage by Group" table appears
6. Can filter by user across all groups

#### Clear Organization (Personal Mode)

1. Click your email in top-right corner
2. Hover over organization name
3. Click "Clear selection"
4. Returns to personal mode
5. Only shows your personal keys and usage

**Context Awareness**:
- Current org/group shown in dropdown with highlight
- Dashboard header shows "(Organization Name)" if selected
- Cannot create keys in "All Groups" mode (must select specific group)

---

### Flow 5: Debugging Failed Requests

1. **Notice Issue** → `/dashboard`
   - See drop in requests or spike in errors

2. **Check Provider Health** → `/health-status`
   - Click "Health" in navigation
   - See if any providers are down/degraded
   - Note response times and success rates

3. **Review Logs** → `/logs`
   - Click "Logs" in navigation
   - Look for failed requests (status column)
   - Apply filters to narrow down:
     - Specific API key
     - Time range
     - Provider
     - Model

4. **Inspect Log Details**
   - Click on failed request row
   - Expand to see:
     - Error message
     - Response status code
     - Latency
     - Timestamps

5. **Check Provider Key**
   - If provider-specific error, go to `/providers`
   - Find the provider key used
   - Click "Test" to verify it still works
   - Check if key was revoked or expired

6. **Verify API Key**
   - Go to `/api-keys`
   - Find the Artemis key
   - Check if it's been revoked
   - Review provider overrides

7. **Test in Chat** → `/chat`
   - Use same key/provider/model combination
   - Send test request
   - See real-time error response
   - Helps diagnose configuration issues

8. **Fix and Monitor**
   - Update provider key if expired
   - Adjust configuration
   - Return to `/logs` to verify fixes
   - Watch for successful requests

---

### Flow 6: Revoking Compromised Keys

#### If Artemis API Key Compromised

1. **Revoke Immediately** → `/api-keys`
   - Click "API Keys" in navigation
   - Find the compromised key
   - Click "Revoke" button
   - Confirm action (cannot be undone)

2. **Create Replacement**
   - Click "Create New Key"
   - Use descriptive name (e.g., "Production v2")
   - Copy new key securely

3. **Update Applications**
   - Update all apps using old key
   - Deploy with new key
   - Monitor `/logs` for traffic on new key

4. **Verify Old Key Inactive**
   - Check logs for any requests on old key (should fail)
   - Review "Last Used" timestamp

#### If Provider Key Compromised

1. **Revoke in Artemis** → `/providers`
   - Click "Providers" in navigation
   - Select provider tab
   - Find compromised key
   - Click "Revoke"

2. **Revoke at Provider**
   - Log into OpenAI/Anthropic/etc dashboard
   - Revoke key there as well
   - Generate new key from provider

3. **Add New Provider Key**
   - Click "Add Key" in Artemis
   - Paste new provider key
   - Give it clear name (e.g., "OpenAI Production Key v2")
   - Save

4. **Test New Key**
   - Click "Test" button
   - Verify successful connection

5. **Monitor Usage**
   - Check `/dashboard` for requests using new key
   - Ensure no errors
   - Verify costs are tracking correctly

---

## Navigation Tips

### Quick Access

**Keyboard Navigation**
- `Tab` - Navigate between elements
- `Enter` - Submit forms or click focused button
- `Esc` - Close modals
- Arrow keys - Navigate dropdowns

**Breadcrumb Navigation**
- Dashboard header shows current context: "Dashboard (Organization Name)"
- Group name shown in parentheses if selected
- Helps maintain orientation in hierarchy

### Context Indicators

**Visual Cues**:
- **Active organization** - Highlighted in dropdown (blue text/background)
- **Active group** - Highlighted in dropdown (green text/background)
- **"All Groups" mode** - Shows "All Groups" badge, enables group comparison table
- **No org selected** - Dropdown shows "No organization" in gray

**Page Awareness**:
- Some pages require organization (Groups, Settings)
- Cannot create keys in "All Groups" mode - badge appears
- Filters persist when switching between Dashboard and Logs

### Efficient Workflows

**Use Dropdowns for Context Switching**
- Hover instead of clicking for quick preview
- Nested menus reduce clicks
- Persists across page loads

**Filter Dashboards, Don't Create Multiple Views**
- Use period filters for time ranges
- Use key/provider filters for specific analysis
- Click table rows to auto-filter entire dashboard

**Group Organization Best Practices**
- Create groups by team, not by project
- Use "All Groups" mode for executive overview
- Switch to specific group for operational work

**Naming Conventions**
- API Keys: `[Environment]-[App]-[Version]` (e.g., "Production-WebApp-v2")
- Provider Keys: `[Provider]-[Environment]-[Date]` (e.g., "OpenAI-Prod-2024Q4")
- Groups: `[Team/Department]` (e.g., "Engineering", "Marketing")
- Organizations: `[Company Name]` (e.g., "AIC Holdings")

---

## Keyboard Shortcuts

### Global

| Shortcut | Action |
|----------|--------|
| `Esc` | Close any open modal or dropdown |
| `Tab` | Navigate to next focusable element |
| `Shift + Tab` | Navigate to previous focusable element |
| `Enter` | Submit focused form or click focused button |

### Dashboard

| Shortcut | Action |
|----------|--------|
| `r` | Refresh data (future feature) |
| `f` | Focus on filter dropdown (future feature) |

### Chat

| Shortcut | Action |
|----------|--------|
| `Ctrl/Cmd + Enter` | Send message |
| `Ctrl/Cmd + K` | Clear chat history |
| `Ctrl/Cmd + /` | Focus message input |

### Tables/Logs

| Shortcut | Action |
|----------|--------|
| `↑` / `↓` | Navigate table rows (when focused) |
| `Enter` | Expand selected row details |
| `n` | Next page (future feature) |
| `p` | Previous page (future feature) |

### Modals

| Shortcut | Action |
|----------|--------|
| `Esc` | Close modal |
| `Tab` | Navigate form fields |
| `Enter` | Submit form (if no multiline fields) |

*Note: Some shortcuts are planned features and may not be implemented yet*

---

## Common Issues & Solutions

### Cannot Create API Keys

**Problem**: "Select a group" error appears

**Solution**:
- You're in "All Groups" mode
- Click user menu → Group dropdown
- Select a specific group
- Try creating key again

### Empty Dashboard

**Problem**: No data showing despite making requests

**Solution**:
1. Check you're viewing correct organization/group
2. Verify API key was used in requests
3. Check time period filter (might be too narrow)
4. Review logs to confirm requests were received

### Provider Key Test Fails

**Problem**: "Test" button shows error

**Solution**:
1. Verify key is correct (not truncated)
2. Check key hasn't been revoked at provider
3. Confirm key has correct permissions
4. Try creating new key from provider

### Cannot See Other User's Keys

**Problem**: Team member's keys not visible

**Solution**:
- This is expected behavior (security)
- Keys are only visible to creator
- Admins can't reveal other users' keys
- Use shared group keys for team access

### Group Not Showing in Dashboard

**Problem**: Created group doesn't appear in dropdown

**Solution**:
1. Refresh page (group context is cached)
2. Verify you were added as member
3. Check you have active organization selected
4. Confirm group wasn't deleted

---

## Advanced Tips

### Cost Optimization

1. **Monitor token usage** - Input tokens are often cheaper than output
2. **Use smaller models** - GPT-4 vs GPT-3.5 cost difference is significant
3. **Set max_tokens** - Prevent runaway costs from long responses
4. **Filter by expensive models** - Dashboard → filter by model → identify costly calls
5. **Use reasoning tokens wisely** - Only for complex tasks that need them

### Security Best Practices

1. **Rotate keys regularly** - Create new, revoke old every 90 days
2. **Use group isolation** - Don't share keys across teams
3. **Monitor unexpected usage** - Check logs for suspicious activity
4. **Revoke unused keys** - Clean up old/test keys
5. **Never commit keys to git** - Use environment variables

### Organizational Structure

**Small Team (1-5 people)**
- Single organization
- Single default group
- Everyone is owner/admin

**Medium Team (5-20 people)**
- Single organization
- Multiple groups by function (Engineering, Marketing, Sales)
- Group admins manage their own keys

**Large Enterprise (20+ people)**
- Multiple organizations (by department or BU)
- Multiple groups per org (by team)
- Strict role hierarchy (owners → admins → members)
- Dedicated admins for key management

---

## API Integration Patterns

### Pattern 1: Drop-in Replacement

**Use Case**: Existing OpenAI/Anthropic code

**Change**: Only update `base_url` and `api_key`

```python
# Before
client = OpenAI(api_key="sk-...")

# After
client = OpenAI(
    base_url="https://artemis.jettaintelligence.com/v1",
    api_key="art_..."
)
```

**Benefits**:
- Zero code changes
- Instant tracking
- Easy to revert

### Pattern 2: Multi-Provider Strategy

**Use Case**: Fallback between providers

**Implementation**:
1. Create multiple provider keys in Artemis
2. Use provider-specific routing via `model` parameter
3. Artemis routes to correct provider automatically

**Example**:
```python
# OpenAI
response = client.chat.completions.create(
    model="gpt-4o",  # Routes to OpenAI
    messages=[...]
)

# Anthropic
response = client.chat.completions.create(
    model="claude-3-5-sonnet-20241022",  # Routes to Anthropic
    messages=[...]
)
```

### Pattern 3: App-Specific Tracking

**Use Case**: Multiple applications sharing Artemis

**Implementation**: Set `X-App-Id` header

```python
client = OpenAI(
    base_url="https://artemis.jettaintelligence.com/v1",
    api_key="art_...",
    default_headers={"X-App-Id": "web-app"}
)
```

**Benefits**:
- Dashboard filters by app
- Cost allocation per application
- Usage trends per app

---

## Troubleshooting Guide

### Error: "Invalid API Key"

**Possible Causes**:
1. Key was revoked
2. Key prefix incorrect (should start with `art_`)
3. Typo in key
4. Key belongs to different organization/group

**Fix**:
- Go to `/api-keys`
- Verify key status
- Copy key again or create new one

### Error: "No provider key found"

**Possible Causes**:
1. No provider key configured for this provider
2. Provider key was revoked
3. Group doesn't have access to provider key

**Fix**:
- Go to `/providers`
- Add provider key for the provider you're calling
- Ensure key is in same group as Artemis API key

### Error: "Rate limit exceeded"

**Possible Causes**:
1. Provider (OpenAI/Anthropic) rate limit hit
2. Too many concurrent requests

**Fix**:
- Check provider dashboard for limits
- Implement exponential backoff
- Use multiple provider keys for load balancing

### Dashboard Not Updating

**Possible Causes**:
1. Time period filter too narrow
2. Wrong organization/group selected
3. Browser cache

**Fix**:
- Change period to "Last 30 days"
- Verify org/group in top-right dropdown
- Hard refresh (Ctrl+Shift+R or Cmd+Shift+R)

---

## Glossary

**Artemis API Key** - The API key your application uses to call Artemis (starts with `art_`)

**Provider Key** - Your actual API key from OpenAI, Anthropic, etc., stored in Artemis

**Provider Account** - Container for provider keys, associates keys with a specific LLM provider

**Group** - Team or sub-organization with isolated keys and usage

**Organization** - Top-level entity representing your company

**Usage Log** - Individual record of an API request

**Token** - Unit of text processing (roughly 4 characters or 0.75 words)

**Latency** - Time from request to response in milliseconds

**Input Tokens** - Tokens in your prompt/request

**Output Tokens** - Tokens in the model's response

**Reasoning Tokens** - Internal tokens used by models like o1 (not visible in output)

**Cache Tokens** - Reused tokens from previous requests (reduces cost)

**X-App-Id** - HTTP header to identify which application is making the request

**SSO** - Single Sign-On via Jetta SSO

**QTD** - Quarter to Date (current quarter's data)

**YTD** - Year to Date (current year's data)

**ITD** - Inception to Date (all time data)

---

## Support & Resources

### Getting Help

**Documentation**
- Setup Guide: `/guide`
- API Docs: `/docs`
- This Navigation Guide

**In-App Support**
- Chat interface for testing: `/chat`
- Health status monitoring: `/health-status`
- Detailed logs: `/logs`

**Contact**
- Built by AIC Holdings
- Support: (contact information)
- GitHub Issues: (repository link)

### Additional Resources

**Provider Documentation**
- [OpenAI API Docs](https://platform.openai.com/docs)
- [Anthropic API Docs](https://docs.anthropic.com)
- [Google AI Docs](https://ai.google.dev)
- [Perplexity Docs](https://docs.perplexity.ai)
- [OpenRouter Docs](https://openrouter.ai/docs)

**Best Practices**
- Cost optimization guides
- Security recommendations
- Integration patterns
- Example code repositories

---

## Version History

**v1.0.0** (December 2025)
- Initial navigation documentation
- Comprehensive page reference
- User flows and examples
- Keyboard shortcuts
- Troubleshooting guide

---

*Last Updated: December 12, 2025*
*Document Version: 1.0.0*
*Artemis Version: 1.0.0*
