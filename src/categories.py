from enum import Enum


class ArxivCategory(str, Enum):
    """arXiv subject categories to extract and index."""

    CS_AI = "cs.AI"          # Artificial Intelligence
    CS_LG = "cs.LG"          # Machine Learning
    CS_CV = "cs.CV"          # Computer Vision and Pattern Recognition
    CS_CL = "cs.CL"          # Computation and Language (NLP)
    CS_NE = "cs.NE"          # Neural and Evolutionary Computing

    @classmethod
    def all(cls) -> list[str]:
        """Return all category values as strings."""
        return [member.value for member in cls]

    @classmethod
    def from_str(cls, value: str) -> "ArxivCategory":
        """Lookup an enum member from its string value."""
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"'{value}' is not a valid {cls.__name__}")
