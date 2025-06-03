# Celline Frontend

This is the Nuxt.js-based frontend for Celline's interactive web interface.

## Setup

The frontend is automatically managed by the `celline run interactive` command. Dependencies will be installed automatically when you first run the interactive mode.

## Manual Setup

If you need to manually set up the frontend:

```bash
cd frontend
npm install
npm run dev
```

## Development

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run generate` - Generate static site
- `npm run preview` - Preview production build

## Features

- **Project Management**: View and manage Celline projects
- **Sample Management**: Add and manage sample data
- **Analysis Tools**: Run analysis workflows through the web interface
- **Real-time Updates**: Live feedback on long-running operations

## Configuration

The frontend automatically connects to the Celline backend. Configuration is handled through the Nuxt config file (`nuxt.config.ts`).