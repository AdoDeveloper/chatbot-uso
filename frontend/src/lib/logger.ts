const isDev = typeof process !== "undefined"
  && process.env.NODE_ENV !== "production";

export const logger = {
  info: (...args: unknown[]) => {
    if (isDev) console.info(...args);
  },
  warn: (...args: unknown[]) => {
    if (isDev) console.warn(...args);
  },
  error: (...args: unknown[]) => {
    if (isDev) console.error(...args);
  },
  debug: (...args: unknown[]) => {
    if (isDev) console.debug(...args);
  },
};

export function routeLogger(context: string) {
  return {
    error: (...args: unknown[]) => {
      if (isDev) console.error(`[${context}]`, ...args);
    },
    warn: (...args: unknown[]) => {
      if (isDev) console.warn(`[${context}]`, ...args);
    },
    info: (...args: unknown[]) => {
      if (isDev) console.info(`[${context}]`, ...args);
    },
  };
}
