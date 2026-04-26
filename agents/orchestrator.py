import os
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from utils.groq_llm import call_llm
from utils.memory import load_memory, save_memory, summarize_memory
from utils.prompts import (
    LEARNING_ROLE, build_learning_prompt,
    CONTEXT_ROLE, build_context_prompt,
)
from utils.exploit_runner import generate_exploit_proof
from agents.hacker import run_hacker
from agents.engineer import run_engineer
from agents.reviewer import run_reviewer

MAX_ITERATIONS = 5
VERDICT_SECURE = "SECURE"

# ── Logging helper ─────────────────────────────────────────────────────────────
def _log(cb, message, color="white", agent="Orchestrator"):
    if cb:
        cb(message, color, agent)

# ── Context Agent ──────────────────────────────────────────────────────────────
def run_context_agent(code: str, log_cb) -> str:
    _log(log_cb, "Analyzing code structure and identifying high-risk areas...", "cyan", "Context")
    # Validate input to prevent IDOR
    if not isinstance(code, str) or len(code) > 3000:
        return "Error: Invalid input"
    summary = call_llm(build_context_prompt(code[:3000]), system_role=CONTEXT_ROLE)
    _log(log_cb, summary[:250] + "...", "cyan", "Context")
    return summary

# ── Learning Agent ─────────────────────────────────────────────────────────────
def run_learning_agent(vuln_report, patched_code, memory_records, log_cb):
    _log(log_cb, "Extracting vulnerability pattern for memory...", "green", "Learning")
    import re
    # Validate input to prevent IDOR
    if not isinstance(vuln_report, str) or not isinstance(patched_code, str):
        return memory_records
    raw = call_llm(build_learning_prompt(vuln_report, patched_code), system_role=LEARNING_ROLE)
    if raw.startswith("Error calling Groq API:"):
        return memory_records

    def _ex(label, text):
        m = re.search(rf"{re.escape(label)}\s*[:\-]?\s*(.+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vulnerability_type": _ex("VULNERABILITY_TYPE", raw),
        "severity": _ex("SEVERITY", raw),
        "pattern": _ex("PATTERN", raw),
        "fix_strategy": _ex("FIX_STRATEGY", raw),
    }
    updated = memory_records + [record]
    save_memory(updated)
    _log(log_cb, f"Pattern stored: [{record['severity']}] {record['vulnerability_type']}", "green", "Learning")
    return updated

# ── Main Pipeline ──────────────────────────────────────────────────────────────
def run_pipeline(
    code: str,
    log_callback: Optional[Callable[[str, str, str], None]] = None,
    phase_callback: Optional[Callable[[str, str], None]] = None,
) -> Dict:
    """4-phase autonomous security pipeline."""
    logs: List[Dict] = []

    def log(msg, color="white", agent="Orchestrator"):
        logs.append({"message": msg, "color": color, "agent": agent})
    