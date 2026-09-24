'use client';

import { forwardRef, type ReactNode } from 'react';
import { TextInput, type TextInputProps } from '@mantine/core';

export interface InputProps extends Omit<TextInputProps, 'leftSection' | 'rightSection'> {
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, error, leftIcon, rightIcon, ...props },
  ref
) {
  return (
    <TextInput
      ref={ref}
      label={label}
      error={error}
      leftSection={leftIcon}
      rightSection={rightIcon}
      {...props}
    />
  );
});

Input.displayName = 'Input';
