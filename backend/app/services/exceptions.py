"""Domain error for missing references.

Error de dominio para referencias inexistentes.
"""


class EntityNotFoundError(Exception):
    """Se lanza cuando una entidad referenciada (FK) no existe en base de datos."""

    def __init__(self, entity_name: str, entity_id) -> None:
        self.entity_name = entity_name
        self.entity_id = entity_id
        super().__init__(f"{entity_name} with id={entity_id} not found")


class TenantForbiddenError(Exception):
    """Se lanza cuando un tenant (marca) intenta acceder o modificar recursos de otra marca (RN-10)."""

    def __init__(self, message: str = "Access denied for this tenant context") -> None:
        super().__init__(message)


class DuplicateTrackingNumberError(Exception):
    """Se lanza cuando se intenta asociar una guía cuyo tracking number ya existe."""

    def __init__(self, tracking_number: str) -> None:
        self.tracking_number = tracking_number
        super().__init__(f"Tracking number '{tracking_number}' is already registered")
