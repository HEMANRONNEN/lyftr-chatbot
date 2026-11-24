from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str
    system_prompt: str | None = Field(default=None, max_length=4000)

    @field_validator("session_id")
    @classmethod
    def session_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("session_id must not be blank")
        return v

    @field_validator("message")
    @classmethod
    def message_length(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 4000:
            raise ValueError("message must be 1-4000 characters after trimming")
        return v

    @field_validator("system_prompt")
    @classmethod
    def blank_prompt_is_none(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return v.strip()
