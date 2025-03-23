from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class DeviceBase(SQLModel):
    user_id: int = Field(foreign_key="user.user_id", index=True)
    fcm_token: Optional[str] = Field(default=None, max_length=255, index=True)
    brand: Optional[str] = Field(default=None, max_length=50)
    model_name: Optional[str] = Field(default=None, max_length=100)
    os_name: Optional[str] = Field(default=None, max_length=20)
    os_version: Optional[str] = Field(default=None, max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Device(DeviceBase, table=True):
    device_id: Optional[int] = Field(default=None, primary_key=True)

class DeviceCreate(DeviceBase):
    pass

class DeviceUpdate(DeviceBase):
    pass