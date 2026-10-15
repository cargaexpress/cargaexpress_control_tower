"""Domain exceptions for core business and persistence rules."""


class EntityNotFoundError(Exception):
    """Raised when a referenced foreign key or domain entity does not exist."""

    def __init__(self, entity_name: str, entity_id) -> None:
        self.entity_name = entity_name
        self.entity_id = entity_id
        super().__init__(f"{entity_name} with id={entity_id} not found")


class TenantForbiddenError(Exception):
    """Raised when a tenant (brand) attempts to access or modify resources of another brand (RN-10)."""

    def __init__(self, message: str = "Access denied for this tenant context") -> None:
        super().__init__(message)


class DuplicateTrackingNumberError(Exception):
    """Raised when attempting to associate a shipping label whose tracking number already exists."""

    def __init__(self, tracking_number: str) -> None:
        self.tracking_number = tracking_number
        super().__init__(f"Tracking number '{tracking_number}' is already registered")
