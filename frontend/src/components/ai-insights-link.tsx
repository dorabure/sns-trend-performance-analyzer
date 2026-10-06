"use client";
import Link from 'next/link';
import { t as tr, displayLabel, intlLocale, errorText } from '../i18n';
import { useLocale } from '../i18n/react';
import { useEffect, useState } from 'react';

export default function AIInsightsLink() {
  useLocale();
  const [href, setHref] = useState('/dashboard/insights');
  useEffect(() => {
    const source = new URLSearchParams(window.location.search), query = new URLSearchParams();
    for (const key of ['platform', 'from', 'to']) if (source.has(key)) query.set(key, source.get(key)!);
    setHref(`/dashboard/insights?${query}`);
  });
  return <Link className="text-teal-800 underline" href={href}>{tr('nav.insights')}</Link>;
}
