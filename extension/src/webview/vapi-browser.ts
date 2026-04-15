import Vapi from '@vapi-ai/web';

// The webview loads `media/vapi.js` via a plain <script> tag, so we expose the
// SDK on window for the existing panel code (which expects `window.Vapi`).
(window as any).Vapi = Vapi;

