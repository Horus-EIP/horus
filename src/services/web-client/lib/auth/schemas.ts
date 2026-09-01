'use client';

import { z } from 'zod';

// The trailing length rule in this regex is also enforced by `.min(10)` below, so a
// too-short password reports the length error rather than the character-class one.
const passwordRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^a-zA-Z0-9]).{10,}$/;

export const loginSchema = z.object({
  username: z
    .string()
    .min(1, 'Username is required'),
  password: z
    .string()
});

export const baseRegisterSchema = z
  .object({
    username: z
      .string()
      .min(1, 'Username is required'),
    password: z
      .string()
      .min(10, 'Password must be at least 10 characters')
      .regex(
        passwordRegex,
        'Password must include uppercase, lowercase, number, and special character'
      ),
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  });

export const registerSchema = baseRegisterSchema.refine(
  (data) => data.password === data.confirmPassword,
  { message: "Passwords don't match", path: ['confirmPassword'] }
);

export const registerField = baseRegisterSchema.shape;

export type LoginFormData = z.infer<typeof loginSchema>;
export type RegisterFormData = z.infer<typeof registerSchema>;
