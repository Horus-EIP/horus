'use client';

import { motion } from 'framer-motion';
import { useMemo } from 'react';

export interface PasswordStrengthProps {
  password: string;
}

export interface PasswordScore {
  score: number;
  label: string;
  color: string;
  percentage: number;
}

export const calculatePasswordScore = (password: string): PasswordScore => {
  if (!password) {
    return { score: 0, label: 'No password', color: 'bg-slate-300', percentage: 0 };
  }

  let score = 0;

  if (password.length >= 8) score += 1; 
  if (password.length >= 12) score += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
  if (/\d/.test(password)) score += 1;
  if (/[^a-zA-Z0-9]/.test(password)) score += 1;

  const labels: Record<number, { label: string; color: string }> = {
    0: { label: 'Very Weak', color: 'bg-red-500' },
    1: { label: 'Weak', color: 'bg-orange-500' },
    2: { label: 'Fair', color: 'bg-yellow-500' },
    3: { label: 'Good', color: 'bg-lime-500' },
    4: { label: 'Strong', color: 'bg-green-500' },
    5: { label: 'Very Strong', color: 'bg-emerald-600' },
  };

  const { label, color } = labels[score] || labels[0];
  const percentage = (score / 5) * 100;

  return { score, label, color, percentage };
};

export const PasswordStrength = ({ password }: PasswordStrengthProps) => {
  const strength = useMemo(() => calculatePasswordScore(password), [password]);

  if (!password) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-600 dark:text-slate-400">Password strength:</span>
        <span className={`font-medium ${
          strength.score <= 1 ? 'text-red-600' :
          strength.score <= 2 ? 'text-yellow-600' :
          strength.score <= 3 ? 'text-lime-600' :
          'text-green-600'
        }`}>
          {strength.label}
        </span>
      </div>
      <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
        <motion.div
          className={`h-full ${strength.color}`}
          initial={{ width: 0 }}
          animate={{ width: `${strength.percentage}%` }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
        />
      </div>
      <ul className="text-xs text-slate-600 dark:text-slate-400 space-y-1">
        <li className={password.length >= 10 ? 'text-green-600' : ''}>
          {password.length >= 10 ? '✓' : '○'} At least 10 characters
        </li>
        <li className={/[a-z]/.test(password) && /[A-Z]/.test(password) ? 'text-green-600' : ''}>
          {/[a-z]/.test(password) && /[A-Z]/.test(password) ? '✓' : '○'} Upper and lowercase letters
        </li>
        <li className={/\d/.test(password) ? 'text-green-600' : ''}>
          {/\d/.test(password) ? '✓' : '○'} At least one number
        </li>
        <li className={/[^a-zA-Z0-9]/.test(password) ? 'text-green-600' : ''}>
          {/[^a-zA-Z0-9]/.test(password) ? '✓' : '○'} Special character
        </li>
      </ul>
    </div>
  );
};
