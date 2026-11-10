from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, description="LAN ID")
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    username: str = Field(description="LAN ID")
    display_name: str
    email: str
    department: str
    title: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Seconds until the token expires")
    user: UserOut
