# Agent Names in Simple English

This guide translates the **technical agent names** in the project into **plain, easy English** so you can understand what each one does.

> **Note:** The code still uses the original technical names. This document is for **your understanding only**.

---

## Quick lookup table

| # | Technical name (in code) | Simple English name | What it does in one line |
|---|--------------------------|---------------------|---------------------------|
| 1 | Accessibility Agent | **Easy-to-use-for-everyone Checker** | Makes sure the site works for people with disabilities (colors, keyboard, screen readers). |
| 2 | Agent Registry Agent | **Team Builder** | Creates or picks helper agents and assigns them tasks. |
| 3 | Code Agent | **File Writer / Website Builder** | Writes the actual website files and saves them to the project. |
| 4 | Code Generator Agent | **Patch Merger** | Combines small changes from helper agents into the main website files. |
| 5 | Commit Agent | **Save Gatekeeper** | Safety rule: files can only be saved after checks pass (not a separate worker). |
| 6 | Component/UI Agent | **UI Parts Planner** | Plans buttons, cards, menus, and other screen pieces. |
| 7 | Content Agent | **Text & Content Planner** | Plans what words, headings, and content go on each page. |
| 8 | Conversation Agent | **Chat Reply Agent** | Replies to greetings and questions without building a website. |
| 9 | Diagnostic UX Agent | **Problem Finder (docs only)** | Label in reports for “find UX problems” — real work done by other agents. |
| 10 | Domain Research Agent | **Industry Research Helper** | Looks up what kind of site fits the business (restaurant, shop, etc.). |
| 11 | Greeting Handler Agent | **Hello / Welcome Agent** | Says hi and asks what website you want. |
| 12 | Intent Analyzer Agent | **Request Type Checker** | Figures out what kind of request the user sent (inside team-building flow). |
| 13 | Intent Router Agent | **Traffic Director** | First agent: decides chat vs build website vs update vs write code file. |
| 14 | Memory Agent | **Project Memory Keeper** | Reads old files, loads past notes, saves new notes for next time. |
| 15 | Planner Agent | **Site Plan Maker** | Decides pages, sections, layout, and structure before coding. |
| 16 | Predictive Planning Agent | **Site Plan Label (docs only)** | Name used in reports for planning — real work done by **Site Plan Maker**. |
| 17 | Prescriptive Builder Agent | **Build Label (docs only)** | Name used in reports for file generation — real work done by **File Writer**. |
| 18 | Preview Agent | **Test Preview Builder** | Builds a temporary preview of the site before saving for real. |
| 19 | Preview QA Agent | **Preview Check Label (registry)** | Registry name for preview + quality checks — runtime uses Preview + Visual QA agents. |
| 20 | Prompt Analyst Agent | **Request Understanding Agent** | Reads your message and turns it into a clear project brief. |
| 21 | Repair Agent | **Fix-it Agent** | Fixes the website when validation or preview fails. |
| 22 | Requirement Analyst Agent | **Needs List Maker** | Lists what the user wants and what is still missing (dynamic flow). |
| 23 | Requirement Confirmation Agent | **Plan Approval Agent** | Shows you the plan and waits for your “yes” before building. |
| 24 | Review Agents | **Quality Review Team (label)** | Group name for UX + accessibility review in safety rules. |
| 25 | Scoped Update Agent | **Small Edit Agent** | Changes only the files that need updating — not the whole site. |
| 26 | Simple Code Writer Agent | **Single File Code Writer** | Writes one code file (Python, Java, etc.) — not a full website. |
| 27 | Supervisor Agent | **Boss / Step Controller** | Chooses which agent runs next and when the job is finished. |
| 28 | Targeted Update Agent | **Tiny Fix Agent** | Very small change only (e.g. change title or one color). |
| 29 | Task Decomposer Agent | **Job Splitter** | Breaks big work into smaller tasks for helper agents. |
| 30 | Universal Error Handling Agent | **Error Doctor** | Reads error messages and guesses which file caused the problem. |
| 31 | Update Analysis Agent | **Update Planner** | Decides how big an update is and which files to touch. |
| 32 | UX Review Agent | **User Experience Checker** | Checks if the plan is easy to use and makes sense for visitors. |
| 33 | UX/Layout Agent | **Layout & Flow Planner** | Plans page layout and how users move through the site. |
| 34 | Validation Agent | **File Checker** | Checks generated files are correct and complete before preview. |
| 35 | Visual QA Agent | **Preview Tester** | Opens preview and checks the site actually runs without errors. |
| 36 | Workflow Planner Agent | **Task Order Planner** | Decides which tasks run first and which can run in parallel. |

---

## Grouped by job (easier to remember)

### 🚦 Start of every request
| Simple name | Technical name |
|-------------|------------------|
| **Traffic Director** | Intent Router Agent |
| **Plan Approval Agent** | Requirement Confirmation Agent *(when confirmation is on)* |

### 💬 Chat only (no website build)
| Simple name | Technical name |
|-------------|------------------|
| **Hello / Welcome Agent** | Greeting Handler Agent |
| **Chat Reply Agent** | Conversation Agent |

### 🏗️ Main website build (most common path)
| Simple name | Technical name | Order |
|-------------|------------------|-------|
| **Boss / Step Controller** | Supervisor Agent | Controls all steps |
| **Project Memory Keeper** | Memory Agent | 1 — read files & memory |
| **Request Understanding Agent** | Prompt Analyst Agent | 2 — understand request |
| **Site Plan Maker** | Planner Agent | 3 — plan site |
| **File Writer / Website Builder** | Code Agent | 4 — write files |
| **File Checker** | Validation Agent | 5 — check files |
| **Test Preview Builder** | Preview Agent | 6 — build preview |
| **Preview Tester** | Visual QA Agent | 7 — test preview |
| **File Writer** *(save)* | Code Agent | 8 — save to project |
| **Project Memory Keeper** *(save notes)* | Memory Agent | 9 — save memory |

### 🔧 Update existing website
| Simple name | Technical name |
|-------------|------------------|
| **Update Planner** | Update Analysis Agent |
| **Error Doctor** | Universal Error Handling Agent |
| **Tiny Fix Agent** | Targeted Update Agent |
| **Small Edit Agent** | Scoped Update Agent |
| **Fix-it Agent** | Repair Agent |

### 👥 Extra helpers (only when full dynamic mode is on)
| Simple name | Technical name |
|-------------|------------------|
| **Team Builder** | Agent Registry Agent |
| **Job Splitter** | Task Decomposer Agent |
| **Task Order Planner** | Workflow Planner Agent |
| **Industry Research Helper** | Domain Research Agent |
| **Text & Content Planner** | Content Agent |
| **UI Parts Planner** | Component/UI Agent |
| **Layout & Flow Planner** | UX/Layout Agent |
| **User Experience Checker** | UX Review Agent |
| **Easy-to-use-for-everyone Checker** | Accessibility Agent |
| **Patch Merger** | Code Generator Agent |

### 📝 One code file only
| Simple name | Technical name |
|-------------|------------------|
| **Single File Code Writer** | Simple Code Writer Agent |

### 🏷️ Names used in reports only (not separate workers)
| Simple name | Technical name |
|-------------|------------------|
| **Problem Finder (label)** | Diagnostic UX Agent |
| **Site Plan Label (label)** | Predictive Planning Agent |
| **Build Label (label)** | Prescriptive Builder Agent |
| **Save Gatekeeper (rule)** | Commit Agent |
| **Quality Review Team (label)** | Review Agents |
| **Preview Check Label** | Preview QA Agent |

---

## Simple story: what happens when you say “Build me a coffee shop website”

1. **Traffic Director** — “This user wants a new website.”
2. **Plan Approval Agent** — “Here is the plan. Do you agree?” *(if confirmation is on)*
3. **Boss** — “Start the build process.”
4. **Project Memory Keeper** — “Let me read what we already have.”
5. **Request Understanding Agent** — “They want a coffee shop site with menu and contact.”
6. **Site Plan Maker** — “Home page, menu section, contact form, warm colors.”
7. **File Writer** — “Here are all the code files.”
8. **File Checker** — “Files look valid.”
9. **Test Preview Builder** — “Preview is ready.”
10. **Preview Tester** — “Preview runs with no errors.”
11. **File Writer** — “Saving files to the project.”
12. **Project Memory Keeper** — “Saving notes for next chat.”
13. **Boss** — “Job done.”

---

## Words that sound technical → simple meaning

| Technical word | Simple meaning |
|----------------|----------------|
| Intent | What the user wants |
| Routing | Sending the request to the right path |
| Orchestration | Overall flow control |
| Scoped update | Small, limited edit |
| Artifact | Generated website files (JSON + code) |
| Validation | Checking files are correct |
| Staged preview | Temporary test version before save |
| Visual QA | Testing the preview in a browser |
| Dynamic agent | Helper created for a specific job |
| Registry | List of available helpers |
| Handoff | One agent passing work to the next |
| MAS / contract | Safety rules for agents |
| Commit | Save files to the project |

---

## Related docs

- [available_agent_names.md](./available_agent_names.md) — full technical list and sources
