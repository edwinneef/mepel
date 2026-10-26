import { createRoot } from 'react-dom/client';
import { App } from './App';
import { EngineClient } from './client';
import './styles.css';
import { OverlayApp } from './OverlayApp';
import { OverlayClient } from './overlay';

const token = document.querySelector<HTMLMetaElement>('meta[name="debug-token"]')?.content ?? '';
createRoot(document.getElementById('root')!).render(window.mapleOverlay
  ? <OverlayApp client={new OverlayClient(token)} /> : <App client={new EngineClient(token)} />);
