#!/usr/bin/env python3
"""
Demo Data Seeding Script

This script populates the Horus system with sample data for demonstration purposes.
It creates:
- Admin user (if not exists)
- Sample conversations
- Sample documents in the Knowledge Store
- Verifies agent connectivity

Usage:
    python seed_demo_data.py --url http://localhost:8000 --ks-url http://localhost:8080

Requirements:
    pip install httpx
"""

import argparse
import asyncio
import json
import sys
import time
from typing import Optional

import httpx

# Demo data configuration
DEMO_USERS = [
    {"username": "demo_user", "password": "demo123", "role": "user"},
    {"username": "demo_manager", "password": "manager123", "role": "manager"},
]

DEMO_CONVERSATIONS = [
    {"name": "Financial Analysis Demo"},
    {"name": "Product Research Demo"},
    {"name": "Customer Support Demo"},
]

DEMO_DOCUMENTS = [
    {
        "id": "demo_q1_report",
        "title": "Q1 2025 Financial Report",
        "content": """
        Q1 2025 Financial Report - Executive Summary
        
        Revenue Performance:
        - Total revenue: $12.5 million (up 18% YoY)
        - Subscription revenue: $8.2 million (up 22% YoY)
        - Professional services: $4.3 million (up 12% YoY)
        
        Key Metrics:
        - Customer acquisition cost (CAC): $245 (down 15%)
        - Customer lifetime value (LTV): $2,850 (up 8%)
        - Monthly recurring revenue (MRR): $2.73 million
        - Net revenue retention: 112%
        
        Regional Performance:
        - North America: $7.5M (60% of total)
        - Europe: $3.1M (25% of total)
        - Asia Pacific: $1.9M (15% of total)
        
        Key Highlights:
        - Launched 3 new enterprise features
        - Expanded to 5 new markets
        - 150 new enterprise customers acquired
        - Customer satisfaction score: 4.6/5.0
        """
    },
    {
        "id": "demo_product_roadmap",
        "title": "Product Roadmap 2025",
        "content": """
        Product Roadmap 2025
        
        Q1 2025 (Completed):
        - Multi-agent orchestration
        - Enhanced RAG pipeline
        - Real-time collaboration features
        
        Q2 2025 (In Progress):
        - Advanced analytics dashboard
        - Custom agent training
        - API rate limiting and quotas
        - Multi-language support (Spanish, French, German)
        
        Q3 2025 (Planned):
        - Enterprise SSO integration
        - Audit logging and compliance
        - Self-service agent deployment
        - Mobile application (iOS/Android)
        
        Q4 2025 (Planned):
        - AI model fine-tuning interface
        - Advanced workflow automation
        - Marketplace for agent templates
        - On-premise deployment option
        """
    },
    {
        "id": "demo_customer_faq",
        "title": "Customer FAQ",
        "content": """
        Frequently Asked Questions
        
        Q: What is Horus?
        A: Horus is an AI-powered multi-agent system that helps organizations automate complex tasks through intelligent agent orchestration.
        
        Q: How does the RAG pipeline work?
        A: The RAG (Retrieval-Augmented Generation) pipeline retrieves relevant documents from the Knowledge Store and uses them to provide context-aware responses.
        
        Q: What models does Horus support?
        A: Horus supports various transformer models including T5, GPT-based models, and custom fine-tuned models. GPU acceleration is available for improved performance.
        
        Q: How secure is the system?
        A: Horus implements role-based access control (RBAC), JWT authentication, encrypted communications, and comprehensive audit logging.
        
        Q: Can I integrate Horus with existing systems?
        A: Yes, Horus provides RESTful APIs and WebSocket support for real-time integration with existing enterprise systems.
        
        Q: What is the pricing model?
        A: Contact our sales team for enterprise pricing. We offer flexible plans based on usage, number of agents, and support level.
        """
    },
    {
        "id": "demo_sales_data",
        "title": "Sales Performance Q1 2025",
        "content": """
        Sales Performance Analysis - Q1 2025
        
        Top Performing Products:
        1. Enterprise Suite: $4.2M (34% of revenue)
        2. Professional Plan: $3.8M (30% of revenue)
        3. Team Plan: $2.5M (20% of revenue)
        4. Starter Plan: $2.0M (16% of revenue)
        
        Sales Team Performance:
        - Team Alpha: $3.1M (124% of quota)
        - Team Beta: $2.8M (112% of quota)
        - Team Gamma: $2.4M (96% of quota)
        - Team Delta: $2.2M (88% of quota)
        
        New Customer Acquisition:
        - Enterprise: 45 new customers
        - Mid-market: 105 new customers
        - SMB: 320 new customers
        
        Pipeline Analysis:
        - Total pipeline value: $28.5M
        - Weighted pipeline: $14.2M
        - Average deal size: $42,000
        - Average sales cycle: 45 days
        
        Churn Analysis:
        - Gross churn: 3.2%
        - Net revenue retention: 112%
        - Expansion revenue: $1.8M
        """
    }
]


class DemoSeeder:
    """Seeds demo data into the Horus system."""
    
    def __init__(self, mas_url: str, ks_url: str, admin_user: str, admin_pass: str):
        self.mas_url = mas_url.rstrip("/")
        self.ks_url = ks_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_pass = admin_pass
        self.token: Optional[str] = None
    
    async def run(self):
        """Run the complete seeding process."""
        print("\n" + "="*60)
        print("🌱 HORUS DEMO DATA SEEDER")
        print("="*60)
        print(f"MAS URL: {self.mas_url}")
        print(f"Knowledge Store URL: {self.ks_url}")
        print("="*60 + "\n")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Authenticate
            print("1️⃣  Authenticating...")
            if not await self._authenticate(client):
                print("   ❌ Authentication failed!")
                return False
            print("   ✅ Authenticated as admin\n")
            
            # Step 2: Check system health
            print("2️⃣  Checking system health...")
            if not await self._check_health(client):
                print("   ⚠️  Some services may be unavailable\n")
            else:
                print("   ✅ All services healthy\n")
            
            # Step 3: Seed Knowledge Store documents
            print("3️⃣  Seeding Knowledge Store documents...")
            docs_created = await self._seed_documents(client)
            print(f"   ✅ Created {docs_created}/{len(DEMO_DOCUMENTS)} documents\n")
            
            # Step 4: Create demo conversations
            print("4️⃣  Creating demo conversations...")
            convs_created = await self._seed_conversations(client)
            print(f"   ✅ Created {convs_created}/{len(DEMO_CONVERSATIONS)} conversations\n")
            
            # Step 5: Verify agents
            print("5️⃣  Checking registered agents...")
            agents = await self._get_agents(client)
            print(f"   ✅ Found {agents} registered agent(s)\n")
            
            # Summary
            print("="*60)
            print("✅ DEMO DATA SEEDING COMPLETE")
            print("="*60)
            print(f"   📚 Documents: {docs_created}")
            print(f"   💬 Conversations: {convs_created}")
            print(f"   🤖 Agents: {agents}")
            print("="*60 + "\n")
            
            return True
    
    async def _authenticate(self, client: httpx.AsyncClient) -> bool:
        """Authenticate and get token."""
        try:
            response = await client.post(
                f"{self.mas_url}/auth/token",
                data={"username": self.admin_user, "password": self.admin_pass}
            )
            if response.status_code == 200:
                self.token = response.json().get("access_token")
                return True
        except Exception as e:
            print(f"   Error: {e}")
        return False
    
    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}
    
    async def _check_health(self, client: httpx.AsyncClient) -> bool:
        """Check system health."""
        healthy = True
        
        # Check MAS
        try:
            response = await client.post(
                f"{self.mas_url}/rabbitmq/heartbeat",
                headers=self._headers()
            )
            if response.status_code != 200:
                print("   ⚠️  MAS health check failed")
                healthy = False
        except Exception:
            print("   ⚠️  Cannot reach MAS")
            healthy = False
        
        # Check Knowledge Store
        try:
            response = await client.get(f"{self.ks_url}/health")
            if response.status_code != 200:
                print("   ⚠️  Knowledge Store health check failed")
                healthy = False
        except Exception:
            print("   ⚠️  Cannot reach Knowledge Store")
            healthy = False
        
        return healthy
    
    async def _seed_documents(self, client: httpx.AsyncClient) -> int:
        """Seed documents into Knowledge Store."""
        created = 0
        for doc in DEMO_DOCUMENTS:
            try:
                response = await client.post(
                    f"{self.ks_url}/store/add",
                    json=doc
                )
                if response.status_code in [200, 201]:
                    created += 1
                    print(f"   📄 Added: {doc['title']}")
                elif response.status_code == 409:
                    print(f"   📄 Exists: {doc['title']}")
                    created += 1
                else:
                    print(f"   ❌ Failed: {doc['title']} ({response.status_code})")
            except Exception as e:
                print(f"   ❌ Error adding {doc['title']}: {e}")
        return created
    
    async def _seed_conversations(self, client: httpx.AsyncClient) -> int:
        """Create demo conversations."""
        created = 0
        for conv in DEMO_CONVERSATIONS:
            try:
                response = await client.post(
                    f"{self.mas_url}/conversations/create",
                    headers=self._headers(),
                    json=conv
                )
                if response.status_code in [200, 201]:
                    created += 1
                    print(f"   💬 Created: {conv['name']}")
                else:
                    print(f"   ⚠️  Could not create: {conv['name']}")
            except Exception as e:
                print(f"   ❌ Error: {e}")
        return created
    
    async def _get_agents(self, client: httpx.AsyncClient) -> int:
        """Get number of registered agents."""
        try:
            response = await client.get(
                f"{self.mas_url}/agents/",
                headers=self._headers()
            )
            if response.status_code == 200:
                agents = response.json()
                if isinstance(agents, list):
                    for agent in agents[:5]:
                        status = agent.get("status", "unknown")
                        name = agent.get("name", "Unknown")
                        print(f"   🤖 {name}: {status}")
                    return len(agents)
        except Exception:
            pass
        return 0


async def main():
    parser = argparse.ArgumentParser(description="Seed demo data into Horus")
    parser.add_argument("--url", default="http://localhost:8000", help="MAS API URL")
    parser.add_argument("--ks-url", default="http://localhost:8080", help="Knowledge Store URL")
    parser.add_argument("--admin-user", default="admin", help="Admin username")
    parser.add_argument("--admin-pass", default="admin", help="Admin password")
    
    args = parser.parse_args()
    
    seeder = DemoSeeder(args.url, args.ks_url, args.admin_user, args.admin_pass)
    success = await seeder.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
