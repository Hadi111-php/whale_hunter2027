import { PumpDumpApp } from './app.js';

const app = new PumpDumpApp();
globalThis.pumpLab = app;
app.start().catch(error => console.error('[pump-lab] startup failed:', error));
