# IP-SAKTI Sahayak - Agent Instructions

## Session Recovery Protocol

When starting a new session, you MUST:

1. Read this AGENTS.md file
2. Read PROJECT_STATUS.md
3. Read TODO.md
4. Read the latest entries in DEVELOPMENT_LOG.md
5. Inspect git status
6. Inspect repository structure
7. Determine the last VERIFIED feature
8. Continue from the next unfinished task
9. Never assume code is complete merely because it was generated
10. Never overwrite working functionality without a reason

## Development Principles

- **Real functionality over mock functionality**
- **Evidence over hallucination**
- **Verified sources over invented sources**
- **Product Version context over generic AI answers**
- **Persistent project logs over agent memory**
- **Tests before phase completion**
- **Preserve working code**

## Important Rules

1. Never mark a feature VERIFIED without testing it
2. Never claim completion without verification
3. Never fabricate sources, citations, or data
4. Never commit secrets to the repository
5. Never move to the next phase before current phase is VERIFIED
6. Always maintain project state files (PROJECT_STATUS.md, DEVELOPMENT_LOG.md, TODO.md)
7. Repository files are the source of truth, not conversational memory

## Architecture Reference

For complete architecture and requirements, see:
`IP-SAKTI-Sahayak-Backend-Master-Prompt.txt`

## Current Phase

See PROJECT_STATUS.md for current phase and status.
