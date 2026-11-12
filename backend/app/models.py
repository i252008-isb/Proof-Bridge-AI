
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    Text,
    Float,
    DateTime,
    ForeignKey,
    Numeric,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def current_time():
    return datetime.now(timezone.utc)


# ==========================================
# 1. USER MODEL
# ==========================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time
    )

    projects_as_freelancer: Mapped[list["Project"]] = relationship(
        back_populates="freelancer",
        foreign_keys="Project.freelancer_id"
    )

    projects_as_client: Mapped[list["Project"]] = relationship(
        back_populates="client",
        foreign_keys="Project.client_id"
    )


# ==========================================
# 2. PROJECT MODEL
# ==========================================

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="created")

    freelancer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    agreement_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    agreement_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    amount: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    paypal_order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time
    )

    freelancer: Mapped["User"] = relationship(
        back_populates="projects_as_freelancer",
        foreign_keys=[freelancer_id]
    )

    client: Mapped["User"] = relationship(
        back_populates="projects_as_client",
        foreign_keys=[client_id]
    )

    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    analysis_results: Mapped[list["AnalysisResult"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    status_logs: Mapped[list["CaseStatusLog"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    reports: Mapped[list["Report"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    human_reviews: Mapped[list["HumanReview"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    paypal_transactions: Mapped[list["PayPalTransaction"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


# ==========================================
# 3. REQUIREMENT MODEL
# ==========================================

class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="requirements")


# ==========================================
# 4. EVIDENCE MODEL
# ==========================================

class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time
    )

    project: Mapped["Project"] = relationship(back_populates="evidence")


# ==========================================
# 5. AI ANALYSIS RESULT MODEL
# ==========================================

class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))

    requirement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("requirements.id"), nullable=True
    )

    evidence_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("evidence.id"), nullable=True
    )

    classification: Mapped[str] = mapped_column(String(100))
    similarity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    report_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=current_time, nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="analysis_results")


# ==========================================
# 6. CASE STATUS LOG MODEL
# ==========================================

class CaseStatusLog(Base):
    __tablename__ = "case_status_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    status: Mapped[str] = mapped_column(String(50))
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    changed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time
    )

    project: Mapped["Project"] = relationship(back_populates="status_logs")


# ==========================================
# 7. INVESTIGATION REPORT MODEL
# ==========================================

class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    content: Mapped[dict] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time
    )

    project: Mapped["Project"] = relationship(back_populates="reports")


# ==========================================
# 8. HUMAN REVIEW MODEL
# ==========================================

class HumanReview(Base):
    __tablename__ = "human_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    decision: Mapped[str] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time
    )

    project: Mapped["Project"] = relationship(back_populates="human_reviews")


# ==========================================
# 9. PAYPAL TRANSACTION MODEL
# ==========================================

class PayPalTransaction(Base):
    __tablename__ = "paypal_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))

    paypal_transaction_id: Mapped[str] = mapped_column(
        String(255), unique=True, index=True
    )

    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(50))
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=current_time
    )

    project: Mapped["Project"] = relationship(back_populates="paypal_transactions")
