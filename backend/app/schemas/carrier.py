from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CarrierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    carrier_id: int
    name: str
    integration_type: str
    status: str
    created_at: datetime | None = None
