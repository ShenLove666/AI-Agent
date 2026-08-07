from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10000)
    conversation_id: str | None = None
    rag_enabled: bool = True
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=16, le=8192)
    request_id: str | None = Field(default=None, min_length=8, max_length=64)
    deep_thinking: bool = False
    knowledge_base_ids: list[int] = Field(default_factory=list)
    turn_id: int | None = Field(default=None, gt=0)
    regenerate: bool = False


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: list[dict]
    rewritten_query: str | None = None
    turn_id: int | None = None
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    version: int | None = None
