from abc import ABC, abstractmethod
from enum import StrEnum
from os import PathLike

from app.dto.normalized import NormalizedRecord, ProviderResult, ValidationError


class CsvDatasetType(StrEnum):
    OWN_POSTS = "OWN_POSTS"
    ACCOUNT_DAILY = "ACCOUNT_DAILY"
    TREND_POSTS = "TREND_POSTS"
    COMPETITOR_POSTS = "COMPETITOR_POSTS"


class ProviderFileError(Exception):
    """Fatal input error. Partial results must not be consumed."""

    def __init__(self, error: ValidationError):
        self.error = error
        super().__init__(error.message)


class RowValidationError(Exception):
    def __init__(self, errors: list[ValidationError]):
        self.errors = errors
        super().__init__("Record validation failed")


class DataProvider(ABC):
    @abstractmethod
    def read(self, path: str | PathLike[str], dataset_type: CsvDatasetType) -> ProviderResult[NormalizedRecord]:
        """Read a selected dataset and return valid DTOs and structured row errors."""
