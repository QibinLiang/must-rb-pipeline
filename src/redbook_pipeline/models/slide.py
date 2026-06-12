from typing import List, Optional, Union
from pydantic import BaseModel, Field


class PaperStructure(BaseModel):
    """Structured analysis of a paper, output from PaperAnalyzerSkill."""

    one_line_summary: str = Field(description="One-line summary in Chinese")
    research_background: str = Field(description="Research background")
    core_problem: str = Field(description="Core problem the paper solves")
    key_contributions: List[str] = Field(default_factory=list)
    methodology_points: List[str] = Field(default_factory=list)
    key_results: List[str] = Field(default_factory=list)
    limitations: Union[str, List[str]] = Field(default="")
    recommended_slide_count: int = Field(default=10, ge=8, le=16)
    target_audience: str = Field(default="")


class SlideContent(BaseModel):
    """Content for a single slide."""

    slide_index: int = Field(description="Slide number in template (1-16)")
    slide_type: str = Field(
        description="Type: title, toc, paper_info, background, objective, results, methods, discussion, ending"
    )
    title: str = Field(description="Slide title in Chinese")
    subtitle: Optional[str] = Field(default=None, description="Subtitle (for title slide)")
    presenter: Optional[str] = Field(default=None, description="Presenter info (for title slide)")
    bullet_points: List[str] = Field(default_factory=list, description="Bullet points")
    narration_script: str = Field(description="Spoken narration script in Chinese")
    image_path: Optional[str] = Field(
        default=None,
        description="Path to the image that should be displayed on this slide (relative to job dir)",
    )
    image_caption: Optional[str] = Field(
        default=None, description="Caption for the displayed image"
    )


class PresentationContent(BaseModel):
    """Complete presentation content, output from SlideGeneratorSkill."""

    presentation_title: str = Field(description="Chinese title for the presentation")
    english_title: Optional[str] = Field(default=None)
    presenter_info: Optional[str] = Field(default=None)
    presenter_date: Optional[str] = Field(default=None, description="Presentation date for cover slide")
    total_slides: int
    slides: List[SlideContent]
    estimated_total_duration_seconds: int = Field(default=0)
