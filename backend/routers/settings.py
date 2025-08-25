from fastapi import APIRouter
from ..schemas.settings import SettingsUpdate, SettingsOut
from ..providers.base import settings_state

router = APIRouter()

@router.get("/", response_model=SettingsOut)
def get_settings():
    # Ensure default language key present
    if 'language' not in settings_state:
        settings_state['language'] = 'en'
    return SettingsOut(**settings_state)

@router.post("/", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate):
    for k, v in payload.model_dump(exclude_unset=True).items():
        settings_state[k] = v
    if 'language' not in settings_state:
        settings_state['language'] = 'en'
    return SettingsOut(**settings_state)
