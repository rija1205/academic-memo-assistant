"""SQLAlchemy models for authentication and the academic workspace."""

from app.models.assistant import (
    AssistantCitation,
    AssistantConversation,
    AssistantMessage,
)
from app.models.audit import AcademicAudit
from app.models.auth import (
    AuthAccount,
    AuthSession,
    OAuthConnection,
    PasswordResetToken,
)
from app.models.bibliography import (
    BibliographicReference,
    ReferenceAuthor,
    ReferenceTag,
    ReferenceTagLink,
)
from app.models.citation import (
    Citation,
    CitationItem,
)
from app.models.export import DocumentExport
from app.models.project import Project, ProjectMember
from app.models.rag import RagChunk, RagDocument, RagQuery
from app.models.security import (
    AdminAuditEvent,
    SecurityEvent,
)
from app.models.source import (
    Source,
    SourceBlock,
    SourceFile,
    SourceFolder,
    SourcePage,
    SourceProcessingJob,
    SourceTag,
)
from app.models.user import User
from app.models.workspace import OutlineNode, Section, SectionRevision
from app.models.writing import WritingCitation, WritingGeneration

__all__ = [
    "AssistantCitation",
    "AssistantConversation",
    "AssistantMessage",
    "AuthAccount",
    "AcademicAudit",
    "AdminAuditEvent",
    "BibliographicReference",
    "Citation",
    "CitationItem",
    "DocumentExport",
    "SecurityEvent",
    "AuthSession",
    "OAuthConnection",
    "PasswordResetToken",
    "Project",
    "ProjectMember",
    "RagChunk",
    "RagDocument",
    "RagQuery",
    "Source",
    "SourceBlock",
    "SourceFile",
    "SourceFolder",
    "SourcePage",
    "SourceProcessingJob",
    "SourceTag",
    "ReferenceAuthor",
    "ReferenceTag",
    "ReferenceTagLink",
    "User",
    "OutlineNode",
    "WritingCitation",
    "WritingGeneration",
    "Section",
    "SectionRevision",
]
