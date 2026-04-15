"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const web_1 = __importDefault(require("@vapi-ai/web"));
// The webview loads `media/vapi.js` via a plain <script> tag, so we expose the
// SDK on window for the existing panel code (which expects `window.Vapi`).
window.Vapi = web_1.default;
//# sourceMappingURL=vapi-browser.js.map