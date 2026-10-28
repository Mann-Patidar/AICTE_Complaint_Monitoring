from datetime import datetime, date, timezone
from typing import Optional
from sqlmodel import SQLModel, Field

def utc_now():
    return datetime.now(timezone.utc)

class Officer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    role: str = "Administrator"
    bureau: str = "Regulation Bureau (RB)"
    region: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)

class Institution(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    institution_code: str = Field(index=True, unique=True)
    aicte_permanent_id: Optional[str] = Field(default=None, index=True, unique=True)
    name: str = Field(index=True)
    address: str = ""
    state: str = "Madhya Pradesh"
    district: str = ""
    region: str = "Central"
    institution_type: str = "Engineering College"
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)

class Complaint(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: str = Field(index=True, unique=True)
    institution_id: int = Field(foreign_key="institution.id", index=True)
    title: str
    description: str
    category: str = "Other"
    source: str = "Online"
    received_at: date = Field(default_factory=date.today, index=True)
    current_status: str = Field(default="Received", index=True)
    priority: str = "Normal"
    current_bureau: str = "Regulation Bureau (RB)"
    assigned_officer: str = "Unassigned"
    expected_disposal_at: Optional[date] = None
    disposed_at: Optional[date] = None
    created_at: datetime = Field(default_factory=utc_now)

class CaseAction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    complaint_id: int = Field(foreign_key="complaint.id", index=True)
    officer_name: str = "System"
    action_type: str
    remarks: str = ""
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

class OverlapAlert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    institution_id: int = Field(foreign_key="institution.id", index=True)
    case_ids: str
    alert_type: str = "Same institution across bureaus"
    explanation: str
    review_status: str = Field(default="New", index=True)
    resolution_remarks: str = ""
    created_at: datetime = Field(default_factory=utc_now)

class CoordinationRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    coordination_code: str = Field(index=True, unique=True)
    institution_id: int = Field(foreign_key="institution.id")
    linked_cases: str
    owner: str = "Unassigned"
    reason: str
    status: str = "Awaiting Review"
    next_action: str = "Review linked cases"
    due_at: Optional[date] = None
    created_at: datetime = Field(default_factory=utc_now)

class Notification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    notification_type: str
    message: str
    related_case: Optional[str] = None
    is_read: bool = False
    created_at: datetime = Field(default_factory=utc_now)

class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_email: str = "system"
    action: str
    entity_type: str
    entity_id: str = ""
    details: str = ""
    created_at: datetime = Field(default_factory=utc_now)
