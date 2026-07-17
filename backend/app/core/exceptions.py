from __future__ import annotations

from fastapi import status


class DomainError(Exception):
    """Base para errores de dominio que se traducen a una respuesta HTTP.

    Los routers deben lanzar las subclases concretas (NotFoundError, etc.)
    en vez de HTTPException directamente, para que el mapeo a status code y
    el formato de respuesta queden centralizados en un único exception
    handler (ver app/main.py) en lugar de repetidos por cada endpoint.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT


class ValidationError(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT


class ForbiddenError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
