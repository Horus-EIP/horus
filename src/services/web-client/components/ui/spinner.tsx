'use client';

import { Loader, type LoaderProps } from '@mantine/core';

export function Spinner(props: LoaderProps) {
  return <Loader size="sm" {...props} />;
}
