"""A job posting, normalized across applicant-tracking systems."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Job:
    source: str                 # greenhouse | lever | ashby
    company: str                # the company's board name on that system, e.g. "anthropic"
    id: str                     # the posting's id on that system
    title: str
    url: str
    company_name: str = ""
    locations: list[str] = field(default_factory=list)
    remote: bool | None = None  # the posting's own remote flag, when it has one
    department: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str = ""
    posted: datetime | None = None
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.company}:{self.id}"

    @property
    def display_company(self) -> str:
        return self.company_name or self.company

    def pay(self) -> str:
        if self.salary_min is None:
            return ""
        cur = "" if self.currency in ("", "USD") else f" {self.currency}"
        low, high = self.salary_min, self.salary_max or self.salary_min
        return f"${low / 1000:.0f}K–${high / 1000:.0f}K{cur}" if high != low else f"${low / 1000:.0f}K{cur}"

    def age_days(self, now: datetime | None = None) -> int | None:
        if not self.posted:
            return None
        now = now or datetime.now(timezone.utc)
        return max(0, (now - self.posted).days)

    def to_text(self) -> str:
        """The posting as one document: what a scorer (or a person tailoring a resume) reads."""
        head = [f"# {self.title}", f"Company: {self.display_company}"]
        if self.locations:
            head.append(f"Location: {'; '.join(self.locations)}")
        if self.pay():
            head.append(f"Pay: {self.pay()}")
        head.append(f"URL: {self.url}")
        return "\n".join(head) + "\n\n" + self.description.strip() + "\n"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posted"] = self.posted.isoformat() if self.posted else None
        d["key"] = self.key
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Job:
        d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if d.get("posted"):
            d["posted"] = datetime.fromisoformat(d["posted"])
        return cls(**d)
