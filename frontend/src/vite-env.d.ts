/// <reference types="vite/client" />

/** Injetado em build por `vite.config.ts` (versão do package.json). */
declare const __APP_VERSION__: string

interface ImportMetaEnv {
  /** Mesmo valor que `API_KEY` no `.env` do backend (mín. 32 caracteres). */
  readonly VITE_API_KEY?: string
  /** Base da API (default `/api`). Só altere se o proxy for diferente. */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
