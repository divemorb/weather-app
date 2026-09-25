@dataclass
class ModelForecast:
    name: str
    next_hour_precip_mm: float  # sum of next 60 min (from minutely_15: sum of 4 values)

def model_probability(models: list[ModelForecast], threshold=0.1) -> ModelResult:
    n_rain = sum(1 for m in models if m.next_hour_precip_mm > threshold)
    score = 100 * n_rain / len(models)