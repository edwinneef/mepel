# Local workbench

React/TypeScript replaces the everyday debugger page. Python serves the built files;
Node is needed only when developing or rebuilding this interface.

```powershell
cd ui
npm ci
npm test
npm run build
```

The build writes `src/maplebot/static/workbench/` in the parent project. Start the
application with the existing `run.ps1`, then open `http://127.0.0.1:8765/`.
The original debugger remains at `/legacy` during the migration.

The Python server injects its local token into the HTML. The client uses versioned
status, frame IDs and command envelopes. Tests use fake responses and DOM fixtures;
they never attach to a game or send keyboard input.
