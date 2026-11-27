from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

Role = Literal["admin", "developer", "user"]
Username = Annotated[str, StringConstraints(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]
LoginPassword = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: Username
    password: LoginPassword


class CreateUser(Input):
    username: Username
    display_name: Name
    password: Password
    role: Role = "user"


class UpdateUser(Input):
    display_name: Name
    role: Role
    is_active: bool
    password: Password | None = None


class ChangePassword(Input):
    current_password: LoginPassword
    new_password: Password


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    role: Role
    is_active: bool
    created_at: datetime


class UserPage(BaseModel):
    items: list[UserView]
    total: int
