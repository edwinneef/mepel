from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Rectangle must have positive dimensions")

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2

    @property
    def feet(self) -> float:
        return self.y + self.height

    def contains(self, other: "Rect") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and other.x + other.width <= self.x + self.width
            and other.y + other.height <= self.y + self.height
        )

    def translated(self, dx: float, dy: float) -> "Rect":
        return Rect(round(self.x + dx), round(self.y + dy), self.width, self.height)

    def iou(self, other: "Rect") -> float:
        width = max(0, min(self.x + self.width, other.x + other.width) - max(self.x, other.x))
        height = max(0, min(self.feet, other.feet) - max(self.y, other.y))
        intersection = width * height
        return intersection / (self.width * self.height + other.width * other.height - intersection)
