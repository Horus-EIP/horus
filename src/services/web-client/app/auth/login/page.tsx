'use client';

import { useState } from "react";
import { useForm } from "@tanstack/react-form";
import { motion, AnimatePresence } from "framer-motion";
import { Mail, Lock, AlertCircle, User } from "lucide-react";
import { AuthLayout } from "@/components/auth/auth-layout";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { loginSchema } from "@/lib/auth/schemas";
import { useAuth } from "@/components/auth/auth-provider";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useNotification } from "@/contexts/notification-context";

export default function LoginPage() {
  const { login } = useAuth();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const router = useRouter();
  const { error: notifyError } = useNotification();

  const form = useForm({
    defaultValues: {
      username: "",
      password: "",
    },
    onSubmit: async ({ value }) => {
      setIsSubmitting(true);
      setAuthError(null);

      try {
        const result = await login(value.username, value.password);

        if (result.ok) {
          router.push("/dashboard");
        } else {
          const message = typeof result.error === 'string' 
            ? result.error 
            : "Login failed";
          setAuthError(message);
        }
      } catch (e) {
        const message = "Unexpected error: " + String(e);
        setAuthError(message);
        notifyError(message);
      } finally {
        setIsSubmitting(false);
      }
    },
  });

  return (
    <AuthLayout title="Welcome" subtitle="Sign in to your account">
      
      <AnimatePresence mode="wait">
        {authError && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg"
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
            onChange: ({ value }) => {
              const result = loginSchema.shape.username.safeParse(value);
              return result.success ? undefined : result.error.issues[0].message;
            },
          }}
        >
          {(field) => (
            <div>
              <Input
                type="text"
                label="Username"
                placeholder="Enter your username"
                leftIcon={<User className="w-5 h-5" />}
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                error={field.state.meta.errors.length ? field.state.meta.errors.join(", ") : undefined}
              />
            </div>
          )}
        </form.Field>

        <form.Field
          name="password"
          validators={{
            onChange: ({ value }) => {
              const result = loginSchema.shape.password.safeParse(value);
              return result.success ? undefined : result.error.issues[0].message;
            },
          }}
        >
          {(field) => (
            <div>
              <Input
                type="password"
                label="Password"
                placeholder="Enter your password"
                leftIcon={<Lock className="w-5 h-5" />}
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                error={field.state.meta.errors.length ? field.state.meta.errors.join(", ") : undefined}
                autoComplete="current-password"
              />
            </div>
          )}
        </form.Field>

        <div className="flex items-center justify-between ">
          <a href="#">
            <p className="text-sm text-slate-600 dark:text-slate-400 hover:underline cursor-pointer">
              Forgot password?
            </p>
          </a>
        </div>

        <Button
          type="submit"
          variant="default"
          className="w-full hover:cursor-pointer"
          disabled={isSubmitting}
        >
          {isSubmitting ? "Signing in..." : "Sign in"}
        </Button>
      </form>

      <p className="text-center text-sm text-slate-600 dark:text-slate-400">
        Don&apos;t have an account{" "}
        <Link href="/auth/register">
          <span className="text-white hover:text-white font-medium transition-colors hover:underline">
            Sign up
          </span>
        </Link>
      </p>
    </AuthLayout>
  );
};
