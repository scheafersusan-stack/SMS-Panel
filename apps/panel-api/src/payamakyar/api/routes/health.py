from fastapi import APIRouter

router = APIRouter()


@router.get("/panel/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
