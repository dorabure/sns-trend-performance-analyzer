"use client";
import Link from 'next/link';
import { t as tr, displayLabel, intlLocale, errorText } from '../i18n';
import { useLocale } from '../i18n/react';
import { useEffect, useState } from 'react';

export default function OverviewLink() {
  useLocale();
  const [href, setHref] = useState('/dashboard');
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const filters = new URLSearchParams();
    for (const key of ['platform', 'from', 'to']) if (query.has(key)) filters.set(key, query.get(key)!);
    setHref(`/dashboard?${filters}`);
  });
  return <Link className="font-semibold text-teal-800 underline" href={href}>{tr('nav.overview')}</Link>;
}
