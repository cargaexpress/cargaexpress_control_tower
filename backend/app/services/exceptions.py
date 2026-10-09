"""Domain error for missing references.

Error de dominio para referencias inexistentes.
"""


class EntityNotFoundError(Exception):
    """Se lanza cuando una entidad referenciada (FK) no existe en base de datos."""

    def __init__(self, entity_name: str, entity_id) -> None:
        self.entity_name = entity_name
        self.entity_id = entity_id
        super().__init__(f"{entity_name} with id={entity_id} not found")
