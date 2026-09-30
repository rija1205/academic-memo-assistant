from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ProjectStatus = Literal["draft", "in_progress", "completed", "archived"]
EducationLevel = Literal["licence", "master", "doctorat", "other"]
OutlineKind = Literal["section", "subsection"]
SectionStatus = Literal["empty", "in_progress", "complete"]


class ProjectCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    domain: str | None = Field(default=None, max_length=255)
    institution: str | None = Field(default=None, max_length=255)
    education_level: EducationLevel = "other"
    author_name: str | None = Field(default=None, max_length=200)
    supervisor_name: str | None = Field(default=None, max_length=200)
    academic_year: str | None = Field(default=None, max_length=32)
    problem_statement: str | None = Field(default=None, max_length=20000)
    general_objective: str | None = Field(default=None, max_length=20000)
    specific_objectives: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    thesis_type: str = Field(default="academic", max_length=64)
    bibliography_style: str = Field(default="apa", max_length=64)


class ProjectUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    domain: str | None = Field(default=None, max_length=255)
    institution: str | None = Field(default=None, max_length=255)
    education_level: EducationLevel | None = None
    author_name: str | None = Field(default=None, max_length=200)
    supervisor_name: str | None = Field(default=None, max_length=200)
    academic_year: str | None = Field(default=None, max_length=32)
    problem_statement: str | None = Field(default=None, max_length=20000)
    general_objective: str | None = Field(default=None, max_length=20000)
    specific_objectives: list[str] | None = None
    hypotheses: list[str] | None = None
    keywords: list[str] | None = None
    thesis_type: str | None = Field(default=None, max_length=64)
    bibliography_style: str | None = Field(default=None, max_length=64)
    status: ProjectStatus | None = None


class ProjectSummaryResponse(BaseModel):
    id: UUID
    title: str
    domain: str | None
    status: ProjectStatus
    access_role: str
    education_level: EducationLevel
    institution: str | None
    author_name: str | None
    supervisor_name: str | None
    academic_year: str | None
    thesis_type: str
    bibliography_style: str
    progress: float
    section_count: int
    completed_sections: int
    in_progress_sections: int
    empty_sections: int
    source_count: int
    reference_count: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ProjectResponse(ProjectSummaryResponse):
    problem_statement: str | None
    general_objective: str | None
    specific_objectives: list[str]
    hypotheses: list[str]
    keywords: list[str]


class ProjectAccessResponse(BaseModel):
    project_id: UUID
    role: str = Field(description="owner, editor or reader")


class DuplicateProjectRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)


class OutlineNodeCreateRequest(BaseModel):
    parent_id: UUID | None = None
    kind: OutlineKind = "section"
    title: str = Field(min_length=1, max_length=300)
    position: int | None = Field(default=None, ge=0, le=10000)


class OutlineNodeUpdateRequest(BaseModel):
    parent_id: UUID | None = None
    kind: OutlineKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    position: int | None = Field(default=None, ge=0, le=10000)


class OutlineMove(BaseModel):
    node_id: UUID
    parent_id: UUID | None = None
    position: int = Field(ge=0, le=10000)


class OutlineReorderRequest(BaseModel):
    moves: list[OutlineMove] = Field(min_length=1)


class OutlineNodeResponse(BaseModel):
    id: UUID
    project_id: UUID
    parent_id: UUID | None
    section_id: UUID
    kind: OutlineKind
    title: str
    position: int
    created_at: datetime
    updated_at: datetime


class SectionResponse(BaseModel):
    id: UUID
    project_id: UUID
    outline_node_id: UUID
    title: str
    content: dict[str, Any]
    plain_text: str
    status: SectionStatus
    word_count: int
    version: int
    last_saved_by: UUID | None
    created_at: datetime
    updated_at: datetime


class SectionContentUpdateRequest(BaseModel):
    content: dict[str, Any]
    plain_text: str = Field(default="", max_length=2_000_000)
    status: SectionStatus | None = None
    expected_version: int | None = Field(default=None, ge=1)
    change_summary: str | None = Field(default=None, max_length=500)


class SectionRevisionResponse(BaseModel):
    id: UUID
    section_id: UUID
    project_id: UUID
    version: int
    title: str
    content: dict[str, Any]
    plain_text: str
    word_count: int
    status: SectionStatus
    change_summary: str | None
    created_by: UUID | None
    restored_from_id: UUID | None
    created_at: datetime


class RestoreRevisionRequest(BaseModel):
    change_summary: str | None = Field(default=None, max_length=500)
