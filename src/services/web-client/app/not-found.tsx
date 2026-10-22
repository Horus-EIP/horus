'use client';

import Link from "next/link";
    
export default function NotFoundPage() {

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--bg)] text-[var(--text)] px-4">
      <h1 className="text-4xl font-bold mb-2">404</h1>
      <p className="text-lg mb-6 text-[var(--textSoft)] text-center">
        Oops! The page you were trying to access could not be found.
      </p>

      <div className="flex gap-3">
        <Link
          href="/dashboard"
          className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-700"
        >
          Go to home
        </Link>
      </div>
    </div>
  );
};
