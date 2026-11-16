from pydantic import BaseModel, Field


class LockBudgetInput(BaseModel):
    total_epsilon: float = Field(gt=0, le=1000)


class GrantInput(BaseModel):
    user_email: str = Field(min_length=3, max_length=150)
    dataset_id: int


class DpQueryInput(BaseModel):
    dataset_id: int
    epsilon: float
    query_key: str = Field(min_length=4, max_length=80)
