"""
Knowledge Store Load Testing

Load tests for the Knowledge Store service.

Usage:
    locust -f knowledge_store_load.py --host=http://localhost:8080 \
           --users 50 --spawn-rate 5 --run-time 5m
"""

import random
import time

from locust import HttpUser, between, task


# Sample queries for testing
SAMPLE_QUERIES = [
    "What is the quarterly revenue?",
    "Tell me about sales performance",
    "What are the key business metrics?",
    "Summarize the financial report",
    "What is the growth rate?",
    "Who are the top customers?",
    "What products are performing well?",
    "What is the market share?",
    "Tell me about employee satisfaction",
    "What are the operational costs?",
]

# Sample documents for testing
SAMPLE_DOCS = [
    {
        "title": "Q1 Financial Report",
        "content": "The company reported strong Q1 results with revenue of $10M, representing a 15% increase year-over-year. Key drivers include expansion into new markets and improved customer retention."
    },
    {
        "title": "Sales Analysis",
        "content": "Sales performance exceeded expectations in all regions. North America led with 25% growth, followed by Europe at 18%. The sales team closed 150 new enterprise accounts."
    },
    {
        "title": "Product Update",
        "content": "The new product line launched in March has been well received. Customer feedback indicates high satisfaction with the improved features and user experience."
    },
]


class KnowledgeStoreUser(HttpUser):
    """
    Simulates typical Knowledge Store usage:
    - Queries (most common)
    - Document additions (less common)
    - Health checks
    """
    
    wait_time = between(0.5, 3)
    
    @task(10)
    def query_documents(self):
        """Query the knowledge store (high frequency)."""
        query = random.choice(SAMPLE_QUERIES)
        with self.client.post(
            "/store/query",
            json={"query": query, "k": 5},
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # No results is OK
                response.success()
            else:
                response.failure(f"Status: {response.status_code}")
    
    @task(2)
    def add_document(self):
        """Add a document (medium frequency)."""
        doc = random.choice(SAMPLE_DOCS).copy()
        doc["id"] = f"load_test_{random.randint(10000, 99999)}_{time.time()}"
        
        with self.client.post(
            "/store/add",
            json=doc,
            catch_response=True
        ) as response:
            if response.status_code in [200, 201]:
                response.success()
            else:
                response.failure(f"Status: {response.status_code}")
    
    @task(1)
    def health_check(self):
        """Health check (low frequency)."""
        self.client.get("/health")


class QueryOnlyUser(HttpUser):
    """
    User that only performs queries.
    Useful for testing query performance under load.
    """
    
    wait_time = between(0.1, 1)  # Fast queries
    
    @task
    def query(self):
        """Query with varying complexity."""
        query = random.choice(SAMPLE_QUERIES)
        k = random.choice([3, 5, 10])  # Vary number of results
        
        self.client.post(
            "/store/query",
            json={"query": query, "k": k}
        )


class BurstUser(HttpUser):
    """
    User that creates burst traffic.
    Useful for testing system behavior under sudden load.
    """
    
    wait_time = between(0.01, 0.1)  # Very fast bursts
    
    @task
    def burst_query(self):
        """Rapid-fire queries."""
        self.client.post(
            "/store/query",
            json={"query": random.choice(SAMPLE_QUERIES), "k": 3}
        )
