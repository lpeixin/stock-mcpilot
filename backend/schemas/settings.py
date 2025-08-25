from pydantic import BaseModel, Field

class SettingsUpdate(BaseModel):
    mode: str | None = Field(None, pattern="^(local|cloud)$")
    api_key: str | None = None
    local_model: str | None = None
    language: str | None = Field(None, pattern="^(en|zh)$")

class SettingsOut(SettingsUpdate):
    mode: str
    api_key: str | None = None
    local_model: str | None = None
    language: str | None = Field('en', pattern="^(en|zh)$")
