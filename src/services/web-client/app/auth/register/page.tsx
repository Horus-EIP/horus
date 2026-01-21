'use client';

import { useState } from 'react';
import { useForm } from '@tanstack/react-form';
import { motion, AnimatePresence } from 'framer-motion';
import { User, Mail, Lock, AlertCircle } from 'lucide-react';
import { AuthLayout } from '@/components/auth/auth-layout';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { PasswordStrength } from '@/components/auth/password-strength';
import { registerField } from '@/lib/auth/schemas';
import { useAuth } from '@/components/auth/auth-provider';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useNotification } from '@/contexts/notification-context';

export default function RegisterPage() {
  const { register } = useAuth();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const router = useRouter();
  const { error: notifyError, success: notifySuccess } = useNotification();

  const form = useForm({
    defaultValues: {
      username: '',
      password: '',
      confirmPassword: '',
    },
    onSubmit: async ({ value }) => {
      setIsSubmitting(true);
      setAuthError(null);

      try {
        const result = await register(value.username, value.password);
  
        if (result.ok) {
          router.push('/dashboard');
        } else {
          const message = result.error || 'Registration failed';
          setAuthError(message);
          setIsSubmitting(false);
        }
      } catch (e) {
        const message = "Unexpected error during registration: " + e;
        setAuthError(message);
        notifyError(message);
      } finally {
        setIsSubmitting(false);
      }
    },
  });

  return (
    <AuthLayout
      title="Welcome"
      subtitle="Create your account"
    >
      <AnimatePresence mode="wait">
        {authError && (
          <motion.div
            initial={{ opacity: 0, y: -10, x: 0 }}
            animate={{
              opacity: 1,
              y: 0,
              x: [0, -10, 10, -10, 10, 0],
              transition: {
                x: { duration: 0.4, times: [0, 0.2, 0.4, 0.6, 0.8, 1] },
                opacity: { duration: 0.2 },
              },
            }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg"
            role="alert"
          >
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-800 dark:text-red-200">{authError}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          e.stopPropagation();
          form.handleSubmit();
        }}
        className="space-y-4"
      >
        <form.Field
          name="username"
          validators={{
            onChange: registerField.username,
          }}
        >
          {(field) => (
            <div>
              <Input
                type="text"
                label="Username"
                placeholder="Choose a username"
                leftIcon={<User className="w-5 h-5" />}
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                error={field.state.meta.errors?.[0]?.message}
                autoComplete="username"
              />
            </div>
          )}
        </form.Field>

        <form.Field
          name="password"
          validators={{
            onChange: registerField.password,
          }}
        >
          {(field) => (
            <div className="space-y-2">
              <Input
                type="password"
                label="Password"
                placeholder="Create a strong password"
                leftIcon={<Lock className="w-5 h-5" />}
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                error={field.state.meta.errors?.[0]?.message}
                autoComplete="new-password"
              />
              {field.state.value && !field.state.meta.errors?.[0] && (
                <PasswordStrength password={field.state.value} />
              )}
            </div>
          )}
        </form.Field>

        <form.Field
          name="confirmPassword"
          validators={{
            onChangeListenTo: ['password'],
            onChange: ({ value, fieldApi }) => {
              const password = fieldApi.form.getFieldValue('password');
              if (value !== password) {
                return "Passwords don't match";
              }
              return undefined;
            },
          }}
        >
          {(field) => (
            <div>
              <Input
                type="password"
                label="Confirm Password"
                placeholder="Re-enter your password"
                leftIcon={<Lock className="w-5 h-5" />}
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                error={field.state.meta.errors?.[0]}
                autoComplete="new-password"
              />
            </div>
          )}
        </form.Field>

        <Button
          type="submit"
          variant="default"
          className="w-full hover:cursor-pointer"
          disabled={isSubmitting}
        >
          Create account
        </Button>
      </form>

      {/* TODO: Implement oauth later, not priority */}

      <p className="text-center text-sm text-slate-600 dark:text-slate-400">
        Already have an account?{' '}
        <Link
          href="/auth/login"
        >
          <span
            className="text-white hover:text-white dark:text-white-400 dark:hover:text-white-300 font-medium transition-colors hover:underline">
            Sign in
          </span>
        </Link>
      </p>
    </AuthLayout>
  );
};
