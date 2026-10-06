"use client";
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import { errorText } from '../i18n';

/** Also invalidated on unmount: an old project cannot update the new scope. */
export class RequestVersion {
  private version = 0;
  next() { return ++this.version; }
  current(token: number) { return token === this.version; }
}

export function useRead<T>(loader: () => Promise<T>, enabled = true) {
  const [data, setData] = useState<T | null>(null), [loading, setLoading] = useState(enabled), [error, setError] = useState('');
  const version = useRef(new RequestVersion());
  const reload = useCallback(async () => {
    const gate = version.current, token = gate.next();
    setData(null); setError(''); setLoading(enabled);
    if (!enabled) return;
    try { const value = await loader(); if (gate.current(token)) setData(value); }
    catch (e) { if (gate.current(token)) setError(e instanceof ApiError ? e.message : errorText()); }
    finally { if (gate.current(token)) setLoading(false); }
  }, [loader, enabled]);
  useEffect(() => { const gate = version.current; void reload(); return () => { gate.next(); }; }, [reload]);
  return { data, loading, error, reload };
}
