// Use localhost URLs for browser access (client-side)
// Docker internal names (mas, knowledge_store) only work server-side
export const config = {
  orchestratorUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  knowledgeStoreUrl:
    process.env.NEXT_PUBLIC_KNOWLEDGE_STORE_URL ?? "http://localhost:8080",
  wsUrl: process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000",
};
