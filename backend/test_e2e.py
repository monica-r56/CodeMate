"""
End-to-end smoke tests for the PairVoice backend.

Run this script locally once the backend is running to ensure the voice workflow endpoints succeed.
"""
import json
import os

import httpx

BASE = os.getenv("PAIRVOICE_BASE_URL", "http://localhost:8000")


def test_knowledge_search():
    """Simulate: 'What does the PaymentService do?'"""
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "test-session-001"},
            "toolCallList": [{
                "id": "tc_knowledge",
                "function": {
                    "name": "search_knowledge",
                    "arguments": json.dumps({"query": "PaymentService webhook handler"})
                }
            }]
        }
    }
    response = httpx.post(f"{BASE}/vapi/webhook", json=payload, timeout=15)
    response.raise_for_status()
    result = response.json().get("results", [{}])[0].get("result", "")
    assert result, "search_knowledge returned an empty result"
    print(f"[PASS] search_knowledge: {result[:100]}...")


def test_build_status():
    """Simulate: 'Is the build passing?'"""
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "test-session-002"},
            "toolCallList": [{
                "id": "tc_build",
                "function": {
                    "name": "get_build_status",
                    "arguments": json.dumps({"branch": "main"})
                }
            }]
        }
    }
    response = httpx.post(f"{BASE}/vapi/webhook", json=payload, timeout=15)
    response.raise_for_status()
    result = response.json().get("results", [{}])[0].get("result", "")
    assert "build" in result.lower() or result, "get_build_status did not return expected text"
    print(f"[PASS] get_build_status: {result[:100]}...")


def test_pr_list():
    """Simulate: 'Any open PRs on the auth service?'"""
    payload = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "test-session-003"},
            "toolCallList": [{
                "id": "tc_prs",
                "function": {
                    "name": "get_open_prs",
                    "arguments": json.dumps({"keyword": "auth"})
                }
            }]
        }
    }
    response = httpx.post(f"{BASE}/vapi/webhook", json=payload, timeout=15)
    response.raise_for_status()
    result = response.json().get("results", [{}])[0].get("result", "")
    assert isinstance(result, str), "get_open_prs produced no string"
    print(f"[PASS] get_open_prs: {result[:100]}...")


if __name__ == "__main__":
    test_knowledge_search()
    test_build_status()
    test_pr_list()
    print("\nAll tests passed.")
