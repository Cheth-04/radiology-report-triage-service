import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Literal

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: Literal["radiologist", "admin"] = "radiologist"

class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    role: Literal["radiologist", "admin"]
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
