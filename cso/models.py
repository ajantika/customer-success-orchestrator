"""Shared enums, journey state model and validated configuration."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

PRODUCTS = ["tasks", "docs", "support"]
PRODUCT_LABEL = {"tasks": "Tasks", "docs": "Docs", "support": "Support"}


class JourneyState(str, Enum):
    MONITORING = "monitoring"
    GUIDANCE_SENT = "guidance_sent"
    WAITING_FOR_CUSTOMER = "waiting_for_customer"
    PAUSED_UNTIL_ROLLOUT = "paused_until_rollout"
    WAITING_FOR_HUMAN = "waiting_for_human"
    RESOLVED_AWAITING_CHECK = "resolved_awaiting_progress_check"
    COMPLETED = "completed"
    OPTED_OUT = "opted_out"


S = JourneyState
TRANSITIONS: dict[S, set[S]] = {
    S.MONITORING: {S.GUIDANCE_SENT, S.PAUSED_UNTIL_ROLLOUT, S.WAITING_FOR_HUMAN, S.COMPLETED, S.OPTED_OUT},
    S.GUIDANCE_SENT: {S.WAITING_FOR_CUSTOMER, S.MONITORING, S.PAUSED_UNTIL_ROLLOUT, S.WAITING_FOR_HUMAN, S.COMPLETED, S.OPTED_OUT},
    S.WAITING_FOR_CUSTOMER: {S.GUIDANCE_SENT, S.MONITORING, S.PAUSED_UNTIL_ROLLOUT, S.WAITING_FOR_HUMAN, S.COMPLETED, S.OPTED_OUT},
    S.PAUSED_UNTIL_ROLLOUT: {S.MONITORING, S.GUIDANCE_SENT, S.WAITING_FOR_HUMAN, S.COMPLETED, S.OPTED_OUT},
    S.WAITING_FOR_HUMAN: {S.RESOLVED_AWAITING_CHECK, S.COMPLETED, S.OPTED_OUT},
    S.RESOLVED_AWAITING_CHECK: {S.MONITORING, S.GUIDANCE_SENT, S.WAITING_FOR_CUSTOMER, S.WAITING_FOR_HUMAN, S.COMPLETED, S.OPTED_OUT},
    S.COMPLETED: set(),
    S.OPTED_OUT: set(),
}
TERMINAL = {S.COMPLETED.value, S.OPTED_OUT.value}
ACTIVE_STATES = {S.MONITORING.value, S.GUIDANCE_SENT.value, S.WAITING_FOR_CUSTOMER.value, S.RESOLVED_AWAITING_CHECK.value}

STATE_LABEL = {
    "monitoring": "Monitoring",
    "guidance_sent": "Guidance sent",
    "waiting_for_customer": "Waiting for customer",
    "paused_until_rollout": "Paused until rollout",
    "waiting_for_human": "Waiting for human",
    "resolved_awaiting_progress_check": "Resolved, awaiting progress check",
    "completed": "Completed",
    "opted_out": "Opted out",
}


def can_transition(old: str, new: str) -> bool:
    return S(new) in TRANSITIONS[S(old)]


DEFAULT_MILESTONES = {
    "tasks": [
        {"key": "workspace_created", "label": "Workspace created", "enabled": True},
        {"key": "members_invited", "label": "Team members invited", "enabled": True},
        {"key": "first_project_created", "label": "First project created", "enabled": True},
        {"key": "first_task_completed", "label": "First task completed", "enabled": True},
    ],
    "docs": [
        {"key": "workspace_created", "label": "Workspace created", "enabled": True},
        {"key": "integration_connected", "label": "Required integration connected", "enabled": True, "applies_if": "needs_directory"},
        {"key": "first_doc_published", "label": "First document published", "enabled": True},
        {"key": "first_doc_shared", "label": "First document shared with another user", "enabled": True},
    ],
    "support": [
        {"key": "workspace_created", "label": "Service workspace created", "enabled": True},
        {"key": "channel_configured", "label": "Request channel configured", "enabled": True},
        {"key": "first_request_submitted", "label": "First request submitted", "enabled": True},
        {"key": "first_request_resolved", "label": "First request resolved", "enabled": True},
    ],
}

# Search query used to find guidance for each milestone.
MILESTONE_QUERY = {
    ("tasks", "workspace_created"): "create Tasks workspace",
    ("tasks", "members_invited"): "invite team members Tasks",
    ("tasks", "first_project_created"): "create first project Tasks",
    ("tasks", "first_task_completed"): "complete first task Tasks",
    ("docs", "workspace_created"): "create Docs workspace",
    ("docs", "integration_connected"): "connect employee directory Docs",
    ("docs", "first_doc_published"): "publish first document Docs",
    ("docs", "first_doc_shared"): "share document with another person Docs",
    ("support", "workspace_created"): "create service workspace Support",
    ("support", "channel_configured"): "configure request channel Support",
    ("support", "first_request_submitted"): "submit first request Support",
    ("support", "first_request_resolved"): "resolve first request Support",
}


class Settings(BaseModel):
    """Journey policy. These are demo defaults, not universally valid customer-success thresholds."""

    stall_threshold_days: int = Field(5, ge=1, le=30, description="Days without milestone progress after rollout start before outreach")
    max_messages_per_7d: int = Field(2, ge=1, le=7)
    min_hours_between_messages: int = Field(48, ge=0, le=168)
    reminder_interval_days: int = Field(3, ge=1, le=14)
    stale_data_days: int = Field(14, ge=1, le=90)
    max_unanswered_messages: int = Field(3, ge=1, le=6)
    max_agent_steps: int = Field(10, ge=3, le=15)
    stop_on_blocking_case: bool = True
    handoff_on_tried_steps: bool = True
    max_troubleshooting_replies: int = Field(2, ge=1, le=5)
    offer_handoff_when_docs_unsupported: bool = True
    team_integration: str = "Technical Support"
    team_configuration: str = "Technical Support"
    team_docs_gap: str = "Customer Success"
    team_other: str = "Customer Success"
    fault_create_handoff: bool = False  # demo switch that makes the handoff tool fail
    milestones: dict = Field(default_factory=lambda: DEFAULT_MILESTONES)

    @field_validator("min_hours_between_messages")
    @classmethod
    def _gap(cls, v):
        return v

    def team_for(self, category: str) -> str:
        return {
            "integration": self.team_integration,
            "configuration": self.team_configuration,
            "docs_gap": self.team_docs_gap,
        }.get(category, self.team_other)


TEAMS = ["Technical Support", "Customer Success"]
ASSIGNEES = {
    "Technical Support": ["Ari (Tech Support)", "Sam (Tech Support)"],
    "Customer Success": ["Priya (Customer Success)", "Dana (Customer Success)"],
}
