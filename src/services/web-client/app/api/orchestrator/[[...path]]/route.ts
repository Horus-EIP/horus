import { NextRequest, NextResponse } from "next/server";

/**
 * BFF proxy to MAS. Replaces next.config rewrites so upstream redirects (307/308
 * with Location http://mas:8000/...) are followed on the server; the browser never
 * receives internal Docker hostnames.
 */
export const dynamic = "force-dynamic";

const orchestratorBase = (
  process.env.ORCHESTRATOR_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
]);

/** Node fetch decompresses bodies; forwarding these breaks browser JSON parsing. */
const STRIP_FROM_RESPONSE = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
]);

function pathAndQueryFromBffUrl(requestUrl: string): string {
  const u = new URL(requestUrl);
  const prefix = "/api/orchestrator";
  const pathname = u.pathname;

  let rest: string;
  if (pathname === prefix || pathname === `${prefix}/`) {
    rest = "/";
  } else if (pathname.startsWith(`${prefix}/`)) {
    rest = pathname.slice(prefix.length);
  } else {
    rest = "/";
  }

  return `${rest}${u.search}`;
}

async function proxy(request: NextRequest): Promise<Response> {
  const target = `${orchestratorBase}${pathAndQueryFromBffUrl(request.url)}`;

  const forwardHeaders = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      forwardHeaders.set(key, value);
    }
  });

  const method = request.method;
  const hasBody = !["GET", "HEAD"].includes(method);
  const body = hasBody ? await request.arrayBuffer() : undefined;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers: forwardHeaders,
      body: body && body.byteLength > 0 ? body : undefined,
      redirect: "follow",
      // Propagate the client's abort so a navigated-away request stops MAS work
      // instead of running to completion and showing up as "context canceled".
      signal: request.signal,
    });
  } catch (err) {
    // Client aborted (navigation) — nothing is listening; return a benign 499
    // rather than letting it surface as an unhandled rejection.
    if ((err as Error)?.name === "AbortError") {
      return new NextResponse(null, { status: 499 });
    }
    throw err;
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIP_FROM_RESPONSE.has(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export function GET(request: NextRequest) {
  return proxy(request);
}

export function POST(request: NextRequest) {
  return proxy(request);
}

export function PUT(request: NextRequest) {
  return proxy(request);
}

export function PATCH(request: NextRequest) {
  return proxy(request);
}

export function DELETE(request: NextRequest) {
  return proxy(request);
}

export function HEAD(request: NextRequest) {
  return proxy(request);
}

export function OPTIONS(request: NextRequest) {
  return proxy(request);
}
