'use client';

import type { ComponentPropsWithoutRef } from 'react';
import {
  Button as MantineButton,
  type ButtonProps as MantineButtonProps,
} from '@mantine/core';

type LegacyVariant =
  | 'default'
  | 'destructive'
  | 'outline'
  | 'secondary'
  | 'ghost'
  | 'link';

export type ButtonProps = Omit<MantineButtonProps, 'variant'> &
  Pick<ComponentPropsWithoutRef<'button'>, 'type'> & {
    variant?: LegacyVariant | MantineButtonProps['variant'];
  };

const toMantineVariant = (
  v: ButtonProps['variant']
): MantineButtonProps['variant'] => {
  const map: Record<LegacyVariant, MantineButtonProps['variant']> = {
    default: 'filled',
    destructive: 'filled',
    outline: 'outline',
    secondary: 'light',
    ghost: 'subtle',
    link: 'transparent',
  };
  if (v && v in map) return map[v as LegacyVariant];
  return (v as MantineButtonProps['variant']) ?? 'filled';
};

export function Button({ variant = 'default', color, ...props }: ButtonProps) {
  const mv = toMantineVariant(variant);
  const resolvedColor = variant === 'destructive' ? 'red' : color;
  return <MantineButton variant={mv} color={resolvedColor} {...props} />;
}
