import { createRoot } from 'react-dom/client';
import { App } from './App';
import { EngineClient } from './client';
import './styles.css';

const token = document.querySelector<HTMLMetaElement>('meta[name="debug-token"]')?.content ?? '';
createRoot(document.getElementById('root')!).render(<App client={new EngineClient(token)} />);
