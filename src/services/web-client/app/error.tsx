'use client';

import Link from "next/link";
import { useRouter } from "next/navigation";

export default function ErrorPage() {
  const router = useRouter();

  const handleReload = () => {
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--bg)] text-[var(--text)] px-4">
      <div className="max-w-md w-full text-center space-y-4">
        <h1 className="text-4xl font-bold">Something went wrong</h1>
        <p className="text-sm text-[var(--textSoft)]">
          An unexpected error occurred on the server. Please try again in a few
          moments. If the problem persists, you can return to the home page.
        </p>

        <div className="flex flex-col sm:flex-row gap-3 justify-center mt-4">
          <button
            type="button"
            onClick={handleReload}
            className="px-4 py-2 rounded-lg border border-[var(--textSoft)] text-sm hover:bg-[var(--bgSoft)] transition-colors"
          >
            Try again
          </button>

          <Link
            href="/"
            className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700 transition-colors"
          >
            Go to home
          </Link>
        </div>
      </div>
    </div>
  );
};
