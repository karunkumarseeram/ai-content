from pydantic import BaseModel, Field


class Article(BaseModel):
    article_id: str
    title: str
    summary: str
    url: str
    category: str
    source: str


class StoryBeat(BaseModel):
    headline: str = Field(min_length=8, max_length=110)
    narration: str = Field(min_length=20, max_length=400)
    source_ids: list[str] = Field(min_length=1, max_length=4)
    visual_prompt: str = Field(min_length=20, max_length=500)


class NewsDraft(BaseModel):
    opening: str = Field(min_length=5, max_length=180)
    closing: str = Field(min_length=5, max_length=180)
    beats: list[StoryBeat] = Field(min_length=4, max_length=6)

    @property
    def script(self) -> str:
        return " ".join(
            [self.opening, *(beat.narration for beat in self.beats), self.closing]
        )

    @property
    def word_count(self) -> int:
        return len(self.script.split())

