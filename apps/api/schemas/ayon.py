import uuid
from pydantic import BaseModel


class AyonProjectSummary(BaseModel):
    name: str
    code: str
    active: bool
    linked: bool
    freeframe_project_id: uuid.UUID | None = None


class ActivateAyonProjectRequest(BaseModel):
    # Display name for the new FreeFrame project; defaults to the Ayon project name.
    freeframe_project_name: str | None = None
