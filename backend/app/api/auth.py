from fastapi import APIRouter

router = APIRouter(tags=["auth"])


@router.get("/ping")
def auth_ping():
    return {"ok": True}
