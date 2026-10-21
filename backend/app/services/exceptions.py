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


class DuplicateOrderReferenceError(Exception):
    """Raised when an order reference is already registered for its brand."""

    def __init__(self, brand_order_ref: str) -> None:
        self.brand_order_ref = brand_order_ref
        super().__init__(
            f"Order reference '{brand_order_ref}' is already registered for this brand"
        )


class DuplicateMappingError(Exception):
    """Raised when a state mapping violates uniqueness for (carrier_id, raw_status)."""

    def __init__(
        self, message: str = "A mapping already exists for this carrier and status."
    ) -> None:
        super().__init__(message)


class ConcurrentUpdateConflictError(Exception):
    """Raised when concurrent operations conflict during a batch update."""

    def __init__(self, message: str = "Mapping changed during update; please retry.") -> None:
        super().__init__(message)


class InvalidStatusTransitionError(Exception):
    """Raised when an order status transition is invalid according to RN-02 and ADR-002."""

    def __init__(self, current_status: str, new_status: str, message: str | None = None) -> None:
        self.current_status = current_status
        self.new_status = new_status
        self.message = (
            message or f"Invalid status transition from '{current_status}' to '{new_status}'"
        )
        super().__init__(self.message)
