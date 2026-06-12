from typing import List, Optional
from pydantic import BaseModel, Field


class PaperSection(BaseModel):
    name: str = Field(description="Section name, e.g. abstract, introduction")
    content: str = Field(description="Section text content")


class PaperFigure(BaseModel):
    index: int
    caption: str
    page: int


class PaperTable(BaseModel):
    index: int
    caption: str
    page: int


class ExtractedImage(BaseModel):
    """An image extracted from the PDF."""

    index: int = Field(description="Sequential index of the extracted image")
    filename: str = Field(description="Saved filename, e.g. img_001.png")
    page: int = Field(description="Page number where the image was found")
    caption: str = Field(default="", description="Associated caption text if found")
    width: int = Field(default=0, description="Image width in pixels")
    height: int = Field(default=0, description="Image height in pixels")
    image_type: str = Field(
        default="figure",
        description="Type: title_page, table, figure, architecture, text_fallback",
    )


class ExtractedPaper(BaseModel):
    metadata: dict = Field(default_factory=dict, description="Paper metadata")
    sections: List[PaperSection] = Field(default_factory=list)
    figures: List[PaperFigure] = Field(default_factory=list)
    tables: List[PaperTable] = Field(default_factory=list)
    extracted_images: List[ExtractedImage] = Field(
        default_factory=list, description="Images extracted from PDF pages"
    )
    raw_text: str = Field(default="", description="Full raw text for LLM input")
