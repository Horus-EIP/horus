from pydantic import BaseModel


class RegistrationForm(BaseModel):
    name: str
    skills: list[str]


class TaskForm(BaseModel):
    demand: str
    conversation_id: str
    skills_required: list[str]


class TaskResultForm(BaseModel):
    result: str
    conversation_id: str
    agent_id: str
